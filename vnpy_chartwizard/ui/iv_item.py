from datetime import datetime
from typing import Dict, Tuple
from dataclasses import dataclass
import pyqtgraph as pg

from vnpy.chart.base import BAR_WIDTH, PEN_WIDTH, to_int, DOWN_COLOR, UP_COLOR, YELLOW_COLOR, WHITE_COLOR, BLUE_COLOR, \
    GREEN_COLOR, ORANGE_COLOR, RED_COLOR, MAGENTA_COLOR, SPRING_GREEN_COLOR
from vnpy.chart.item import ChartItem
from vnpy.trader.constant import OptionPrevIvType
from vnpy.trader.database import DB_TZ
from vnpy.trader.ui import QtCore, QtGui
from vnpy.trader.object import BarData
from vnpy.chart.manager import BarManager
from vnpy_optionmaster.engine import OptionEngine
from vnpy_optionmaster.base import APP_NAME as OPTION_APP_NAME


@dataclass
class IvDrawItem:
    value: float
    pen: QtGui.QPen
    brush: QtGui.QBrush


class IvItem(ChartItem):
    """"""

    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)

        self.base_pen: QtGui.QPen = pg.mkPen(color=WHITE_COLOR, width=PEN_WIDTH)
        self.zero_pen: QtGui.QPen = pg.mkPen(color=WHITE_COLOR, width=1)

        self.bid_pen: QtGui.QPen = pg.mkPen(color=RED_COLOR, width=PEN_WIDTH)
        self.ask_pen: QtGui.QPen = pg.mkPen(color=DOWN_COLOR, width=PEN_WIDTH)
        self.atm_pen: QtGui.QPen = pg.mkPen(color=YELLOW_COLOR, width=PEN_WIDTH)
        self.n225_vi_pen: QtGui.QPen = pg.mkPen(color=BLUE_COLOR, width=PEN_WIDTH)  # Orange

        self.bid_brush: QtGui.QBrush = pg.mkBrush(color=RED_COLOR)
        self.ask_brush: QtGui.QBrush = pg.mkBrush(color=DOWN_COLOR)
        self.atm_brush: QtGui.QBrush = pg.mkBrush(color=BLUE_COLOR)
        self.n225_vi_brush: QtGui.QBrush = pg.mkBrush(color=BLUE_COLOR)  # Orange

        # delta 0.02 pens/brushes — distinct hues so they stand out from eris bars
        self.delta002_p_pen: QtGui.QPen = pg.mkPen(color=MAGENTA_COLOR, width=PEN_WIDTH)
        self.delta002_c_pen: QtGui.QPen = pg.mkPen(color=ORANGE_COLOR, width=PEN_WIDTH)
        self.delta002_p_brush: QtGui.QBrush = pg.mkBrush(color=MAGENTA_COLOR)
        self.delta002_c_brush: QtGui.QBrush = pg.mkBrush(color=ORANGE_COLOR)

        self.iv_ranges: dict[tuple[int, int], tuple[float, float]] = {}

        self.prev_iv_type: OptionPrevIvType = OptionPrevIvType.SAME_STRIKE

        # Eris IV data
        self.eris_p_strike: Dict[int, int] = {}
        self.eris_c_strike: Dict[int, int] = {}
        self.eris_a_strike: Dict[int, int] = {}

        self.eris_p_delta: Dict[int, float] = {}
        self.eris_c_delta: Dict[int, float] = {}

        self.eris_p_iv: Dict[int, float] = {}
        self.eris_c_iv: Dict[int, float] = {}

        # Delta 0.02 IV data
        self.delta002_p_strike: Dict[int, int] = {}
        self.delta002_c_strike: Dict[int, int] = {}

        self.delta002_p_delta: Dict[int, float] = {}
        self.delta002_c_delta: Dict[int, float] = {}

        self.delta002_p_iv: Dict[int, float] = {}
        self.delta002_c_iv: Dict[int, float] = {}

        self.atm_iv: Dict[int, float] = {}
        self.n225_vi: Dict[int, float] = {}
        # atm_iv 年率から日率に変換
        self.atm_iv_daily: Dict[int, float] = {}

        # Retry tracking: if init produced all-zero values (prev-day data
        # not yet loaded), allow re-init on next access
        self._last_init_attempt: datetime | None = None


    def get_prev_day_option_iv(self, vt_symbol: str, prev_iv_type: OptionPrevIvType, put_strike: int, call_strike: int,
                    atm_strike: int, dt: datetime) -> tuple[float, float, float]:
        op_month = vt_symbol.split('.')[0]
        main_engine = self._manager.main_engine
        option_engine: OptionEngine | None = main_engine.get_engine(OPTION_APP_NAME)

        if option_engine:
            p_iv, c_iv, a_iv = option_engine.get_prev_day_option_iv(
                op_month,
                prev_iv_type,
                put_strike,
                call_strike,
                atm_strike,
                dt
            )
            return p_iv, c_iv, a_iv
        else:
            return 0.0, 0.0, 0.0

    def get_prev_day_n225_vi(self, dt: datetime) -> float:
        main_engine = self._manager.main_engine
        option_engine: OptionEngine | None = main_engine.get_engine(OPTION_APP_NAME)

        if option_engine:
            n225_vi = option_engine.get_prev_day_n225_vi(dt)
            return n225_vi
        else:
            return 0.0


    def _should_reinit(self) -> bool:
        """Check if cache should be cleared and re-initialized."""
        if not self.eris_p_iv:
            return False
        # If majority of values are zero, data was likely incomplete at init
        values = list(self.eris_p_iv.values())
        if not values:
            return False
        zero_count = sum(1 for v in values if v == 0)
        if zero_count / len(values) < 0.5:
            return False  # enough non-zero values, don't reinit
        # Rate-limit retries
        now_dt = datetime.now(DB_TZ)
        if self._last_init_attempt is not None:
            if (now_dt - self._last_init_attempt).total_seconds() < 5:
                return False
        return True

    def _clear_cache(self) -> None:
        """Clear all cached IV dicts to force re-initialization."""
        self.eris_p_iv.clear()
        self.eris_c_iv.clear()
        self.eris_p_strike.clear()
        self.eris_c_strike.clear()
        self.eris_p_delta.clear()
        self.eris_c_delta.clear()
        self.eris_a_strike.clear()
        self.delta002_p_iv.clear()
        self.delta002_c_iv.clear()
        self.delta002_p_strike.clear()
        self.delta002_c_strike.clear()
        self.delta002_p_delta.clear()
        self.delta002_c_delta.clear()
        self.atm_iv.clear()
        self.atm_iv_daily.clear()
        self.n225_vi.clear()
        self.iv_ranges.clear()

    def update_bar(self, bar: BarData) -> None:
        """Override to clear stale zero-valued cache when new bar arrives."""
        if self._should_reinit():
            self._clear_cache()
        super().update_bar(bar)

    def update_history(self, history: list[BarData]) -> None:
        """Override to clear cache when history is reloaded."""
        self._clear_cache()
        super().update_history(history)

    def get_impv_values(self, ix: int) -> tuple[float, float, float, float, float]:
        """"""
        if ix < 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        # Retry init if previous attempt produced mostly zero values
        # (prev-day option data or bar eris data may not have been ready yet)
        if self._should_reinit():
            self._clear_cache()

        # When initialize, calculate all rsi value
        if not self.eris_p_iv:
            self._last_init_attempt = datetime.now(DB_TZ)
            dt: datetime = datetime.now(DB_TZ)
            bars = self._manager.get_all_bars()
            for n, bar in enumerate(bars):
                atm_price = round(bar.close_price / 1000) * 1000
                prev_p_iv, prev_c_iv, prev_a_iv = self.get_prev_day_option_iv(
                    bar.vt_symbol,
                    self.prev_iv_type,
                    bar.eris_p_strike,
                    bar.eris_c_strike,
                    atm_price,
                    dt
                )
                prev_d002_p_iv, prev_d002_c_iv, _ = self.get_prev_day_option_iv(
                    bar.vt_symbol,
                    self.prev_iv_type,
                    bar.delta002_p_strike,
                    bar.delta002_c_strike,
                    atm_price,
                    dt
                )
                prev_n225_vi = self.get_prev_day_n225_vi(dt)

                iv = bar.eris_p_iv
                self.eris_p_iv[n] = (iv - prev_p_iv) * 100.0 if iv is not None and iv != 0 and prev_p_iv else 0
                self.eris_p_strike[n] = bar.eris_p_strike
                self.eris_p_delta[n] = bar.eris_p_delta

                iv = bar.eris_c_iv
                self.eris_c_iv[n] = (iv - prev_c_iv) * 100.0 if iv is not None and iv != 0 and prev_c_iv else 0
                self.eris_c_strike[n] = bar.eris_c_strike
                self.eris_c_delta[n] = bar.eris_c_delta

                iv = bar.delta002_p_iv
                self.delta002_p_iv[n] = (iv - prev_d002_p_iv) * 100.0 if iv is not None and iv != 0 and prev_d002_p_iv else 0
                self.delta002_p_strike[n] = bar.delta002_p_strike
                self.delta002_p_delta[n] = bar.delta002_p_delta

                iv = bar.delta002_c_iv
                self.delta002_c_iv[n] = (iv - prev_d002_c_iv) * 100.0 if iv is not None and iv != 0 and prev_d002_c_iv else 0
                self.delta002_c_strike[n] = bar.delta002_c_strike
                self.delta002_c_delta[n] = bar.delta002_c_delta

                iv = bar.atm_iv
                self.atm_iv[n] = (iv - prev_a_iv) * 100.0 if iv is not None and iv != 0 and prev_a_iv else 0
                self.eris_a_strike[n] = atm_price

                # atm_iv 年率から日率に変換
                self.atm_iv_daily[n] = iv * 100.0 / (252 ** 0.5) if iv is not None and iv != 0 else 0

                iv = bar.n225_vi
                self.n225_vi[n] = (iv - prev_n225_vi) if iv is not None and iv != 0 and prev_n225_vi else 0

        new_bar = True if ix not in self.eris_p_iv else False
        update = False
        if self.eris_p_iv:
            update = True if ix == max(self.eris_p_iv.keys()) else False

        if new_bar or update:
            # Else calculate new value
            bar = self._manager.get_bar(ix)
            atm_price = round(bar.close_price / 1000) * 1000
            dt: datetime = datetime.now(DB_TZ)
            prev_p_iv, prev_c_iv, prev_a_iv = self.get_prev_day_option_iv(
                bar.vt_symbol,
                self.prev_iv_type,
                bar.eris_p_strike,
                bar.eris_c_strike,
                atm_price,
                dt
            )
            prev_d002_p_iv, prev_d002_c_iv, _ = self.get_prev_day_option_iv(
                bar.vt_symbol,
                self.prev_iv_type,
                bar.delta002_p_strike,
                bar.delta002_c_strike,
                atm_price,
                dt
            )
            prev_n225_vi = self.get_prev_day_n225_vi(dt)

            iv = bar.eris_p_iv
            self.eris_p_iv[ix] = (iv - prev_p_iv) * 100.0 if iv is not None and iv != 0 and prev_p_iv else 0
            self.eris_p_strike[ix] = bar.eris_p_strike
            self.eris_p_delta[ix] = bar.eris_p_delta

            iv = bar.eris_c_iv
            self.eris_c_iv[ix] = (iv - prev_c_iv) * 100.0 if iv is not None and iv != 0 and prev_c_iv else 0
            self.eris_c_strike[ix] = bar.eris_c_strike
            self.eris_c_delta[ix] = bar.eris_c_delta

            iv = bar.delta002_p_iv
            self.delta002_p_iv[ix] = (iv - prev_d002_p_iv) * 100.0 if iv is not None and iv != 0 and prev_d002_p_iv else 0
            self.delta002_p_strike[ix] = bar.delta002_p_strike
            self.delta002_p_delta[ix] = bar.delta002_p_delta

            iv = bar.delta002_c_iv
            self.delta002_c_iv[ix] = (iv - prev_d002_c_iv) * 100.0 if iv is not None and iv != 0 and prev_d002_c_iv else 0
            self.delta002_c_strike[ix] = bar.delta002_c_strike
            self.delta002_c_delta[ix] = bar.delta002_c_delta

            iv = bar.atm_iv
            self.atm_iv[ix] = (iv - prev_a_iv) * 100.0 if iv is not None and iv != 0 and prev_a_iv else 0
            self.eris_a_strike[ix] = atm_price

            # atm_iv 年率から日率に変換
            self.atm_iv_daily[ix] = iv * 100.0 / (252 ** 0.5) if iv is not None and iv != 0 else 0

            iv = bar.n225_vi
            self.n225_vi[ix] = (iv - prev_n225_vi) if iv is not None and iv != 0 and prev_n225_vi else 0

        # Return if already calcualted
        if ix in self.eris_p_iv:
            return self.eris_p_iv[ix], self.eris_c_iv[ix], self.atm_iv[ix], self.atm_iv_daily[ix], self.n225_vi[ix]

        return 0.0, 0.0, 0.0, 0.0, 0.0

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        # Create objects
        p_iv, c_iv, atm_iv, atm_iv_daily, n225_vi = self.get_impv_values(ix)
        d002_p_iv = self.delta002_p_iv.get(ix, 0.0)
        d002_c_iv = self.delta002_c_iv.get(ix, 0.0)

        draw_items = [
            IvDrawItem(value=p_iv, pen=self.ask_pen, brush=self.ask_brush),
            IvDrawItem(value=c_iv, pen=self.bid_pen, brush=self.bid_brush),
            IvDrawItem(value=d002_p_iv, pen=self.delta002_p_pen, brush=self.delta002_p_brush),
            IvDrawItem(value=d002_c_iv, pen=self.delta002_c_pen, brush=self.delta002_c_brush),
            IvDrawItem(value=atm_iv, pen=self.atm_pen, brush=self.atm_brush),
            # IvDrawItem(value=n225_vi, pen=self.n225_vi_pen, brush=self.n225_vi_brush),
        ]

        draw_items.sort(key=lambda item: abs(item.value), reverse=True)

        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        # 0 baseline (drawn first so bars overlay it)
        # Span the full unit slot so segments tile continuously across bars.
        painter.setPen(self.zero_pen)
        painter.drawLine(
            QtCore.QPointF(ix - 0.5, 0),
            QtCore.QPointF(ix + 0.5, 0),
        )

        for item in draw_items:
            painter.setPen(item.pen)
            painter.setBrush(item.brush)
            rect = QtCore.QRectF(
                ix - BAR_WIDTH,
                0,
                BAR_WIDTH * 2,
                item.value
            )
            painter.drawRect(rect)

        # ATM daily upper line (these remain as before, they are horizontal)
        painter.setPen(self.base_pen)
        start_point = QtCore.QPointF(ix - BAR_WIDTH, atm_iv_daily * 0.5)
        end_point = QtCore.QPointF(ix + BAR_WIDTH, atm_iv_daily * 0.5)
        painter.drawLine(start_point, end_point)

        # ATM daily lower line
        start_point = QtCore.QPointF(ix - BAR_WIDTH, -atm_iv_daily * 0.5)
        end_point = QtCore.QPointF(ix + BAR_WIDTH, -atm_iv_daily * 0.5)
        painter.drawLine(start_point, end_point)

        min_iv_val = min(n225_vi, atm_iv, p_iv, c_iv, d002_p_iv, d002_c_iv)
        max_iv_val = max(n225_vi, atm_iv, p_iv, c_iv, d002_p_iv, d002_c_iv)
        if max_iv_val > atm_iv_daily * 0.8:
            # upper line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, atm_iv_daily)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, atm_iv_daily)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 0.8:
            # lower line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, -atm_iv_daily)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, -atm_iv_daily)
            painter.drawLine(start_point, end_point)

        if max_iv_val > atm_iv_daily * 1.3:
            # upper line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, atm_iv_daily * 1.5)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, atm_iv_daily * 1.5)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 1.3:
            # lower line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, -atm_iv_daily * 1.5)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, -atm_iv_daily * 1.5)
            painter.drawLine(start_point, end_point)

        if max_iv_val > atm_iv_daily * 1.8:
            # upper line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, atm_iv_daily * 2.0)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, atm_iv_daily * 2.0)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 1.8:
            # lower line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, -atm_iv_daily * 2.0)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, -atm_iv_daily * 2.0)
            painter.drawLine(start_point, end_point)

        if max_iv_val > atm_iv_daily * 2.3:
            # upper line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, atm_iv_daily * 2.5)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, atm_iv_daily * 2.5)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 2.3:
            # lower line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, -atm_iv_daily * 2.5)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, -atm_iv_daily * 2.5)
            painter.drawLine(start_point, end_point)

        if max_iv_val > atm_iv_daily * 2.8:
            # upper line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, atm_iv_daily * 3.0)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, atm_iv_daily * 3.0)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 2.8:
            # lower line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, -atm_iv_daily * 3.0)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, -atm_iv_daily * 3.0)
            painter.drawLine(start_point, end_point)


        # Finish
        painter.end()
        return picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        min_iv, max_iv = self.get_iv_range()
        rect = QtCore.QRectF(
            0,
            min_iv,
            len(self._bar_picutures),
            max_iv - min_iv
        )
        return rect

    def get_y_range( self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:

        min_iv, max_iv = self.get_iv_range(min_ix, max_ix)
        # print(f"get_y_range: {min_ix} - {max_ix} : {min_iv} - {max_iv}")
        return min_iv, max_iv

    def get_iv_range(self, min_ix: float | None = None, max_ix: float | None = None) -> tuple[float, float]:
        """
        Get iv range to show within given index range.
        """
        if not self.eris_p_iv and self._manager.get_count() > 0:
            self.get_impv_values(0)

        if not self.eris_p_iv:
            return -3.0, 3.0

        cnt = len(self.eris_p_iv)
        if min_ix is None or max_ix is None:
            min_ix = 0
            max_ix = cnt - 1
        else:
            min_ix = to_int(min_ix)
            max_ix = to_int(max_ix)
            max_ix = min(max_ix, cnt - 1)

        if min_ix > max_ix:
            return -3.0, 3.0

        buf: tuple[float, float] | None = self.iv_ranges.get((min_ix, max_ix), None)
        if buf:
            return buf

        p_iv_values = list(self.eris_p_iv.values())[min_ix:max_ix + 1]
        p_iv_min = min(p_iv_values)
        p_iv_max = max(p_iv_values)

        c_iv_values = list(self.eris_c_iv.values())[min_ix:max_ix + 1]
        c_iv_min = min(c_iv_values)
        c_iv_max = max(c_iv_values)

        d002_p_values = list(self.delta002_p_iv.values())[min_ix:max_ix + 1] or [0.0]
        d002_p_min = min(d002_p_values)
        d002_p_max = max(d002_p_values)

        d002_c_values = list(self.delta002_c_iv.values())[min_ix:max_ix + 1] or [0.0]
        d002_c_min = min(d002_c_values)
        d002_c_max = max(d002_c_values)


        atm_iv_values = list(self.atm_iv.values())[min_ix:max_ix + 1] or [0.0]
        atm_iv_min = min(atm_iv_values)
        atm_iv_max = max(atm_iv_values)

        # n225_vi_values = list(self.n225_vi.values())[min_ix:max_ix + 1]
        # n225_vi_min = min(n225_vi_values)
        # n225_vi_max = max(n225_vi_values)

        atm_iv_daily_values = list(self.atm_iv_daily.values())[min_ix:max_ix + 1]
        atm_iv_daily_max = max(atm_iv_daily_values) * 0.5 # atm_iv_daily upper line
        atm_iv_daily_min = -atm_iv_daily_max        # atm_iv_daily lower line

        min_iv = min(p_iv_min, c_iv_min, d002_p_min, d002_c_min, atm_iv_min, atm_iv_daily_min)
        max_iv = max(p_iv_max, c_iv_max, d002_p_max, d002_c_max, atm_iv_max, atm_iv_daily_max)

        self.iv_ranges[(min_ix, max_ix)] = (min_iv, max_iv)
        return min_iv, max_iv

    def get_info_text(self, ix: int) -> str:
        """"""
        if ix in self.eris_p_iv:
            p_strike = self.eris_p_strike[ix]
            c_strike = self.eris_c_strike[ix]
            p_iv = self.eris_p_iv[ix]
            c_iv = self.eris_c_iv[ix]
            p_delta = self.eris_p_delta.get(ix)
            c_delta = self.eris_c_delta.get(ix)

            p_strike = int(p_strike) if p_strike is not None else "--------"
            c_strike = int(c_strike) if c_strike is not None else "--------"

            p_delta_str = f"{p_delta:.3f}" if p_delta else "----"
            c_delta_str = f"{c_delta:.3f}" if c_delta else "----"

            put      = f"P{p_delta_str}水({p_strike}) {p_iv:.2f}%"
            call     = f"C{c_delta_str}赤({c_strike}) {c_iv:.2f}%"


            d002_p_strike = self.delta002_p_strike.get(ix)
            d002_c_strike = self.delta002_c_strike.get(ix)
            d002_p_iv = self.delta002_p_iv.get(ix, 0.0)
            d002_c_iv = self.delta002_c_iv.get(ix, 0.0)
            d002_p_delta = self.delta002_p_delta.get(ix)
            d002_c_delta = self.delta002_c_delta.get(ix)

            d002_p_strike_str = int(d002_p_strike) if d002_p_strike else "--------"
            d002_c_strike_str = int(d002_c_strike) if d002_c_strike else "--------"
            d002_p_delta_str = f"{d002_p_delta:.3f}" if d002_p_delta else "----"
            d002_c_delta_str = f"{d002_c_delta:.3f}" if d002_c_delta else "----"

            put002  = f"P{d002_p_delta_str}紫({d002_p_strike_str}) {d002_p_iv:.2f}%"
            call002 = f"C{d002_c_delta_str}橙({d002_c_strike_str}) {d002_c_iv:.2f}%"

            atm_iv = self.atm_iv.get(ix, 0.0)
            atm_strike = self.eris_a_strike.get(ix)
            atm_strike_str = int(atm_strike) if atm_strike is not None else "--------"
            atm = f"ATM青({atm_strike_str}) {atm_iv:.2f}%"

            words: list = [
                put002,
                put,
                atm,
                call,
                call002,
            ]

            text: str = "\n".join(words)
        else:
            text = "IV -"

        return text

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        self.eris_p_iv.clear()
        self.eris_c_iv.clear()
        self.eris_p_delta.clear()
        self.eris_c_delta.clear()
        self.delta002_p_iv.clear()
        self.delta002_c_iv.clear()
        self.delta002_p_delta.clear()
        self.delta002_c_delta.clear()
        self.atm_iv.clear()
        self.iv_ranges.clear()
        super().clear_all()
