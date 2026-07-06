from datetime import datetime, timedelta
from threading import Lock, Thread

from vnpy.event import Event, EventEngine
from vnpy.trader.engine import BaseEngine, MainEngine
from vnpy.trader.constant import Interval
from vnpy.trader.object import BarData, HistoryRequest, ContractData
from vnpy.trader.utility import (
    INTERVAL_HOUR_WINDOW_MAP,
    INTERVAL_WINDOW_MAP,
    extract_vt_symbol,
)
from vnpy.trader.database import get_database, BaseDatabase
from vnpy.trader.datafeed import get_datafeed, BaseDatafeed


APP_NAME = "ChartWizard"

EVENT_CHART_HISTORY = "eChartHistory"


# Option/IV fields that get carried (last-value-wins) when aggregating bars.
_CARRY_FIELDS: tuple[str, ...] = (
    "eris_p_strike", "eris_p_iv", "eris_p_delta",
    "eris_c_strike", "eris_c_iv", "eris_c_delta",
    "delta002_p_strike", "delta002_p_iv", "delta002_p_delta",
    "delta002_c_strike", "delta002_c_iv", "delta002_c_delta",
    "atm_iv", "n225_vi",
)


def _bucket_dt(dt: datetime, interval: Interval) -> datetime | None:
    """Floor a datetime to the start of its bucket for the given interval."""
    if interval in INTERVAL_WINDOW_MAP:
        window: int = INTERVAL_WINDOW_MAP[interval]
        return dt.replace(
            minute=dt.minute - dt.minute % window,
            second=0,
            microsecond=0,
        )
    if interval in INTERVAL_HOUR_WINDOW_MAP:
        window = INTERVAL_HOUR_WINDOW_MAP[interval]
        return dt.replace(
            hour=dt.hour - dt.hour % window,
            minute=0,
            second=0,
            microsecond=0,
        )
    if interval == Interval.DAILY:
        # Session-based daily bar: the night session (17:00+) belongs to the
        # next day's session, so a session spans D-1 17:00 -> D ~15:40 and is
        # labelled with the close day D at midnight. This matches the futures
        # daily bars in the IV time-series chart and the live BarGenerator's
        # 15:45 daily close.
        session_dt: datetime = dt + timedelta(days=1) if dt.hour >= 17 else dt
        return session_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def aggregate_bars(
    bars: list[BarData],
    target_interval: Interval,
) -> list[BarData]:
    """
    Aggregate 1-minute bars into bars of target_interval (x-minute, hour, or daily).
    Returns input unchanged for 1-minute target or unsupported intervals.
    """
    if not bars:
        return bars
    if target_interval == Interval.MINUTE:
        return bars

    aggregated: list[BarData] = []
    window_bar: BarData | None = None

    for bar in bars:
        window_dt = _bucket_dt(bar.datetime, target_interval)
        if window_dt is None:
            return bars

        if window_bar is None or window_bar.datetime != window_dt:
            if window_bar is not None:
                aggregated.append(window_bar)
            window_bar = BarData(
                symbol=bar.symbol,
                exchange=bar.exchange,
                datetime=window_dt,
                interval=target_interval,
                gateway_name=bar.gateway_name,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                pre_close=bar.pre_close,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest,
            )
        else:
            window_bar.high_price = max(window_bar.high_price, bar.high_price)
            window_bar.low_price = min(window_bar.low_price, bar.low_price)
            window_bar.close_price = bar.close_price
            window_bar.volume += bar.volume
            window_bar.turnover += bar.turnover
            window_bar.open_interest = bar.open_interest

        for field in _CARRY_FIELDS:
            setattr(window_bar, field, getattr(bar, field))

    if window_bar is not None:
        aggregated.append(window_bar)

    return aggregated


class ChartWizardEngine(BaseEngine):
    """
    For running chartWizard.
    """

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine) -> None:
        """"""
        super().__init__(main_engine, event_engine, APP_NAME)

        self.datafeed: BaseDatafeed = get_datafeed()
        self.database: BaseDatabase = get_database()

        # Serialize datafeed/database access from background threads.
        # The MT5 datafeed shares a single ZMQ REQ socket across threads,
        # which requires strict alternating send/recv — concurrent queries
        # raise ZMQError("Operation cannot be accomplished in current state").
        self._query_lock: Lock = Lock()

    def query_history(
        self,
        vt_symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime
    ) -> None:
        """"""
        thread: Thread = Thread(
            target=self._query_history,
            args=[vt_symbol, interval, start, end]
        )
        thread.start()

    def _query_history(
        self,
        vt_symbol: str,
        interval: Interval,
        start: datetime,
        end: datetime
    ) -> None:
        """"""
        with self._query_lock:
            symbol, exchange = extract_vt_symbol(vt_symbol)

            req: HistoryRequest = HistoryRequest(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start=start,
                end=end
            )

            contract: ContractData | None = self.main_engine.get_contract(vt_symbol)
            if contract:
                if contract.history_data:
                    data: list[BarData] | None = self.main_engine.query_history(req, contract.gateway_name)
                else:
                    data = self.database.load_bar_data(
                        symbol,
                        exchange,
                        interval,
                        start,
                        end
                    )
                    if not data:
                        data = self._load_aggregated_from_minute(
                            symbol, exchange, interval, start, end
                        )
                    if not data:
                        data = self.datafeed.query_bar_history(req)
            else:
                data = self.database.load_bar_data(
                    symbol,
                    exchange,
                    interval,
                    start,
                    end
                )
                if not data:
                    data = self._load_aggregated_from_minute(
                        symbol, exchange, interval, start, end
                    )

        event: Event = Event(EVENT_CHART_HISTORY, data)
        self.event_engine.put(event)

    def _load_aggregated_from_minute(
        self,
        symbol: str,
        exchange,
        interval: Interval,
        start: datetime,
        end: datetime,
    ) -> list[BarData] | None:
        """Fallback: load 1-minute bars from DB and aggregate to the requested interval."""
        # Already 1-minute, nothing to aggregate.
        if interval == Interval.MINUTE:
            return None
        # Only intervals with a defined bucket are supported.
        if (
            interval not in INTERVAL_WINDOW_MAP
            and interval not in INTERVAL_HOUR_WINDOW_MAP
            and interval != Interval.DAILY
        ):
            return None

        minute_bars: list[BarData] | None = self.database.load_bar_data(
            symbol, exchange, Interval.MINUTE, start, end
        )
        if not minute_bars:
            return None

        return aggregate_bars(minute_bars, interval)
