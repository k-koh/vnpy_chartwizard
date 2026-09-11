from datetime import datetime, time, timedelta
from typing import Dict, Tuple
from dataclasses import dataclass
import pyqtgraph as pg

from vnpy.chart.base import BAR_WIDTH, PEN_WIDTH, to_int, DOWN_COLOR, UP_COLOR, YELLOW_COLOR, WHITE_COLOR, BLUE_COLOR, \
    GREEN_COLOR, ORANGE_COLOR, RED_COLOR, MAGENTA_COLOR, SPRING_GREEN_COLOR, IV_RANGE_WIDTH
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
        # 0 baseline: yellow dotted, matching CandleItem's base line
        self.zero_pen: QtGui.QPen = pg.mkPen(color=YELLOW_COLOR, width=PEN_WIDTH)
        self.zero_pen.setStyle(QtCore.Qt.DotLine)

        # delta 0.02 pens/brushes — distinct hues so they stand out from eris bars
        self.delta002_p_pen: QtGui.QPen = pg.mkPen(color=BLUE_COLOR, width=PEN_WIDTH)
        self.ask_pen: QtGui.QPen = pg.mkPen(color=DOWN_COLOR, width=PEN_WIDTH)
        self.atm_pen: QtGui.QPen = pg.mkPen(color=WHITE_COLOR, width=PEN_WIDTH)
        self.bid_pen: QtGui.QPen = pg.mkPen(color=RED_COLOR, width=PEN_WIDTH)
        self.delta002_c_pen: QtGui.QPen = pg.mkPen(color=YELLOW_COLOR, width=PEN_WIDTH)

        self.delta002_p_brush: QtGui.QBrush = pg.mkBrush(color=BLUE_COLOR)
        self.ask_brush: QtGui.QBrush = pg.mkBrush(color=DOWN_COLOR)
        self.atm_brush: QtGui.QBrush = pg.mkBrush(color=WHITE_COLOR)
        self.bid_brush: QtGui.QBrush = pg.mkBrush(color=RED_COLOR)
        self.delta002_c_brush: QtGui.QBrush = pg.mkBrush(color=YELLOW_COLOR)

        self.iv_ranges: dict[tuple[int, int], tuple[float, float]] = {}

        self.prev_iv_type: OptionPrevIvType = OptionPrevIvType.SAME_STRIKE

        # Whether the delta 0.02 (d002) put/call IV series are drawn and
        # included in the y-range. Toggled from the chart toolbar checkbox.
        self.show_delta002: bool = True

        # Whether to annotate strike-roll bars with a "prev|now" strike label
        # (e.g. "55000|56000"). Toggled from the chart toolbar checkbox.
        self.show_strike_roll: bool = False

        # Value labels drawn beside each series' latest point (pg.TextItem,
        # created lazily once the item has a ViewBox).
        self._value_labels: Dict[str, pg.TextItem] = {}

        # Reusable pool of strike-roll labels (pg.TextItem), positioned at the
        # visible roll bars each paint.
        self._roll_labels: list[pg.TextItem] = []

        # Reusable pool of σ-level labels (±0.5σ, ±1.0σ …) placed at the right
        # edge next to the latest bar's ATM-IV band lines.
        self._sigma_labels: list[pg.TextItem] = []

        # Reusable pool of "IV crash" labels (▼): the first point after each
        # series' max (over the last two sessions) where IV has fallen at least
        # 0.5σ ATM below that max.
        self._crash_labels: list[pg.TextItem] = []

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

        # Each series: (current value, previous-bar value, pen, brush, strike map).
        # The previous value comes from the per-index cache so we can connect
        # consecutive bars into a line. The strike map lets us detect a strike
        # "roll": when this bar's reference strike differs from the previous
        # bar's, the same-strike day-over-day diff is comparing a DIFFERENT
        # strike, so the jump is not a genuine IV move — we flag it (see below).
        series_points: list[tuple[float, float | None, QtGui.QPen, QtGui.QBrush, Dict[int, int]]] = [
            (p_iv, self.eris_p_iv.get(ix - 1), self.ask_pen, self.ask_brush, self.eris_p_strike),
            (c_iv, self.eris_c_iv.get(ix - 1), self.bid_pen, self.bid_brush, self.eris_c_strike),
        ]
        if self.show_delta002:
            series_points += [
                (d002_p_iv, self.delta002_p_iv.get(ix - 1), self.delta002_p_pen, self.delta002_p_brush, self.delta002_p_strike),
                (d002_c_iv, self.delta002_c_iv.get(ix - 1), self.delta002_c_pen, self.delta002_c_brush, self.delta002_c_strike),
            ]
        series_points.append(
            (atm_iv, self.atm_iv.get(ix - 1), self.atm_pen, self.atm_brush, self.eris_a_strike)
        )

        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        # 0 baseline
        painter.setPen(self.zero_pen)
        painter.drawLine(
            QtCore.QPointF(ix - 0.5, 0),
            QtCore.QPointF(ix + 0.5, 0),
        )

        # Draw each series as a circle marker at (ix, value), connected to the
        # previous bar's point by a line (line chart with circle markers).
        # The x/y axes have very different data scales, so size the marker in
        # PIXELS and convert to data units via the view's pixel-per-data ratio
        # → it renders as a (small) circle, not a tall ellipse.
        radius_px: float = 3.0
        radius_x: float = BAR_WIDTH * 0.3
        radius_y: float = BAR_WIDTH * 0.3
        vb = self.getViewBox()
        if vb is not None and vb.width() > 0 and vb.height() > 0:
            (x0, x1), (y0, y1) = vb.viewRange()
            x_span: float = (x1 - x0) or 1.0
            y_span: float = (y1 - y0) or 1.0
            radius_x = radius_px * x_span / vb.width()
            radius_y = radius_px * y_span / vb.height()
        for value, prev_value, pen, brush, strike_map in series_points:
            # Strike roll? This bar's reference strike differs from prev bar's.
            s_now = strike_map.get(ix)
            s_prev = strike_map.get(ix - 1)
            rolled: bool = (
                s_now is not None and s_prev is not None and s_now != s_prev
            )
            # Connecting line from the previous bar's point. On a roll the diff
            # jump is not a real IV move → draw the incoming segment dashed.
            if prev_value is not None:
                if rolled:
                    line_pen = QtGui.QPen(pen)
                    line_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
                    painter.setPen(line_pen)
                else:
                    painter.setPen(pen)
                painter.drawLine(
                    QtCore.QPointF(ix - 1, prev_value),
                    QtCore.QPointF(ix, value),
                )
            # Marker at the current point: filled circle normally, hollow ring
            # at a strike-roll bar.
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush if rolled else brush)
            painter.drawEllipse(QtCore.QPointF(ix, value), radius_x, radius_y)

        # ATM daily upper line (these remain as before, they are horizontal)
        painter.setPen(self.base_pen)
        start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, atm_iv_daily * 0.5)
        end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, atm_iv_daily * 0.5)
        painter.drawLine(start_point, end_point)

        # ATM daily lower line
        start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, -atm_iv_daily * 0.5)
        end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, -atm_iv_daily * 0.5)
        painter.drawLine(start_point, end_point)

        iv_vals: list[float] = [n225_vi, atm_iv, p_iv, c_iv]
        if self.show_delta002:
            iv_vals += [d002_p_iv, d002_c_iv]
        min_iv_val = min(iv_vals)
        max_iv_val = max(iv_vals)
        if max_iv_val > atm_iv_daily * 0.8:
            # upper line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, atm_iv_daily * 1.0)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, atm_iv_daily * 1.0)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 0.8:
            # lower line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, -atm_iv_daily * 1.0)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, -atm_iv_daily * 1.0)
            painter.drawLine(start_point, end_point)

        if max_iv_val > atm_iv_daily * 1.3:
            # upper line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, atm_iv_daily * 1.5)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, atm_iv_daily * 1.5)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 1.3:
            # lower line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, -atm_iv_daily * 1.5)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, -atm_iv_daily * 1.5)
            painter.drawLine(start_point, end_point)

        if max_iv_val > atm_iv_daily * 1.8:
            # upper line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, atm_iv_daily * 2.0)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, atm_iv_daily * 2.0)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 1.8:
            # lower line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, -atm_iv_daily * 2.0)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, -atm_iv_daily * 2.0)
            painter.drawLine(start_point, end_point)

        if max_iv_val > atm_iv_daily * 2.3:
            # upper line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, atm_iv_daily * 2.5)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, atm_iv_daily * 2.5)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 2.3:
            # lower line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, -atm_iv_daily * 2.5)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, -atm_iv_daily * 2.5)
            painter.drawLine(start_point, end_point)

        if max_iv_val > atm_iv_daily * 2.8:
            # upper line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, atm_iv_daily * 3.0)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, atm_iv_daily * 3.0)
            painter.drawLine(start_point, end_point)
        elif min_iv_val < -atm_iv_daily * 2.8:
            # lower line
            start_point = QtCore.QPointF(ix - IV_RANGE_WIDTH, -atm_iv_daily * 3.0)
            end_point = QtCore.QPointF(ix + IV_RANGE_WIDTH, -atm_iv_daily * 3.0)
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

        min_candidates: list[float] = [p_iv_min, c_iv_min, atm_iv_min, atm_iv_daily_min]
        max_candidates: list[float] = [p_iv_max, c_iv_max, atm_iv_max, atm_iv_daily_max]
        if self.show_delta002:
            min_candidates += [d002_p_min, d002_c_min]
            max_candidates += [d002_c_max, d002_p_max]
        min_iv = min(min_candidates)
        max_iv = max(max_candidates)

        # Add headroom so an extreme latest point (and its value label, which
        # sits at that point's height) isn't clipped at the top/bottom edge.
        span: float = max_iv - min_iv
        pad: float = span * 0.08 if span > 0 else 0.1
        min_iv -= pad
        max_iv += pad

        self.iv_ranges[(min_ix, max_ix)] = (min_iv, max_iv)
        return min_iv, max_iv

    def set_show_delta002(self, show: bool) -> None:
        """Toggle the d002 series; clear caches so bars and y-range recompute."""
        if self.show_delta002 == show:
            return
        self.show_delta002 = show
        self.iv_ranges.clear()
        # Invalidate cached bar pictures WITHOUT dropping the keys: the base
        # paint loop indexes _bar_picutures[ix] and bounds max_ix by its len,
        # so clearing the dict would blank the whole item.
        self._bar_picutures = {ix: None for ix in self._bar_picutures}
        self._item_picuture = None
        self.update()

    def set_show_strike_roll(self, show: bool) -> None:
        """Toggle the strike-roll (prev|now) labels."""
        if self.show_strike_roll == show:
            return
        self.show_strike_roll = show
        self.update()

    def paint(self, painter, opt, w) -> None:
        """Draw the item, then (re)position the latest-point value labels."""
        super().paint(painter, opt, w)
        self._update_value_labels()
        self._update_roll_labels()
        self._update_sigma_labels()
        self._update_crash_labels()

    @staticmethod
    def _session_key(dt: datetime) -> tuple:
        """Identify which trading session a bar belongs to, using the same
        16:00 (night) / 08:00 (day) boundaries as the session lines.

          16:00–23:59  → that date's night session
          00:00–07:59  → the PREVIOUS date's night session
          08:00–15:59  → that date's day session
        """
        t = dt.time()
        if t >= time(16, 0):
            return (dt.date(), "N")
        if t < time(8, 0):
            return ((dt - timedelta(days=1)).date(), "N")
        return (dt.date(), "D")

    def _last_two_session_ix(self) -> list[int]:
        """Return the bar indices belonging to the current + previous session
        (scanning back from the latest bar; stops before the 3rd session)."""
        count: int = self._manager.get_count()
        if count == 0:
            return []
        result: list[int] = []
        distinct: list[tuple] = []
        for ix in range(count - 1, -1, -1):
            bar = self._manager.get_bar(ix)
            if bar is None:
                continue
            key = self._session_key(bar.datetime)
            if distinct and distinct[-1] == key:
                result.append(ix)
                continue
            if len(distinct) == 2:      # a 3rd session → stop
                break
            distinct.append(key)
            result.append(ix)
        result.reverse()
        return result

    def _update_crash_labels(self) -> None:
        """Mark, for each of Put / Call / ATM, how far IV has crashed from its
        max over the current + previous session, in 0.5σ ATM steps. The first
        point that reaches −0.5σ below the max is labelled ▼0.5σ, the first to
        reach −1.0σ is ▼1σ, −1.5σ → ▼1.5σ, and so on (one label per new deeper
        step reached; a single big drop is tagged with the deepest step)."""
        vb = self.getViewBox()
        if vb is None or not self.eris_p_iv:
            for lbl in self._crash_labels:
                lbl.hide()
            return

        window: list[int] = self._last_two_session_ix()
        if not window:
            for lbl in self._crash_labels:
                lbl.hide()
            return

        # (tag, value map, colour) — matches the value-label colours.
        specs: list[tuple[str, Dict[int, float], tuple]] = [
            ("P", self.eris_p_iv, DOWN_COLOR),
            ("C", self.eris_c_iv, RED_COLOR),
            ("A", self.atm_iv, WHITE_COLOR),
        ]

        entries: list[tuple[int, float, tuple, str]] = []
        for tag, value_map, color in specs:
            pts: list[tuple[int, float]] = [
                (ix, value_map[ix]) for ix in window if ix in value_map
            ]
            if len(pts) < 2:
                continue
            # Max IV and its (latest) bar over the window.
            max_ix, max_iv = pts[0]
            for ix, iv in pts:
                if iv >= max_iv:
                    max_iv, max_ix = iv, ix
            # 0.5σ ATM IV変動値 (one step) at the peak.
            step: float = self.atm_iv_daily.get(max_ix, 0.0) * 0.5
            if step <= 0:
                continue
            # Walk forward from the peak; each time IV reaches a new, deeper
            # 0.5σ step below the max, label that bar with the deepest step.
            reached: int = 0
            for ix, iv in pts:
                if ix <= max_ix:
                    continue
                drop: float = max_iv - iv
                if drop < step:
                    continue
                steps: int = int(drop // step)
                if steps > reached:
                    reached = steps
                    mult: float = steps * 0.5
                    entries.append((ix, iv, color, f"{tag}▼{mult:g}σ"))

        while len(self._crash_labels) < len(entries):
            lbl = pg.TextItem(anchor=(0.5, 0.0))
            lbl.setFont(QtGui.QFont("Arial", 9))
            vb.addItem(lbl, ignoreBounds=True)
            self._crash_labels.append(lbl)

        for i, lbl in enumerate(self._crash_labels):
            if i >= len(entries):
                lbl.hide()
                continue
            ix, iv, color, text = entries[i]
            lbl.setColor(color)
            lbl.setText(text)
            lbl.setPos(ix, iv)
            lbl.show()

    def _update_sigma_labels(self) -> None:
        """Place ±0.5σ/±1.0σ… labels next to the latest bar's ATM-IV band
        lines. Mirrors the ladder drawn in _draw_bar_picture: ±0.5σ always,
        then each higher level only on the side whose IV extreme has broken
        through. Hidden entirely when the latest bar has no ATM-IV band."""
        vb = self.getViewBox()
        if vb is None or not self.eris_p_iv:
            for lbl in self._sigma_labels:
                lbl.hide()
            return

        last_ix: int = max(self.eris_p_iv.keys())
        atm_iv_daily: float = self.atm_iv_daily.get(last_ix, 0.0)
        if atm_iv_daily <= 0:
            for lbl in self._sigma_labels:
                lbl.hide()
            return

        p_iv = self.eris_p_iv.get(last_ix, 0.0)
        c_iv = self.eris_c_iv.get(last_ix, 0.0)
        atm_iv = self.atm_iv.get(last_ix, 0.0)
        n225_vi = self.n225_vi.get(last_ix, 0.0)
        iv_vals: list[float] = [n225_vi, atm_iv, p_iv, c_iv]
        if self.show_delta002:
            iv_vals += [
                self.delta002_p_iv.get(last_ix, 0.0),
                self.delta002_c_iv.get(last_ix, 0.0),
            ]
        max_iv_val = max(iv_vals)
        min_iv_val = min(iv_vals)

        # (text, y-value) — ±0.5σ always, then the one-per-block ladder.
        entries: list[tuple[str, float]] = [
            ("+0.5σ", atm_iv_daily * 0.5),
            ("-0.5σ", -atm_iv_daily * 0.5),
        ]
        for th, mult in ((0.8, 1.0), (1.3, 1.5), (1.8, 2.0), (2.3, 2.5), (2.8, 3.0)):
            if max_iv_val > atm_iv_daily * th:
                entries.append((f"+{mult:.1f}σ", atm_iv_daily * mult))
            elif min_iv_val < -atm_iv_daily * th:
                entries.append((f"-{mult:.1f}σ", -atm_iv_daily * mult))

        while len(self._sigma_labels) < len(entries):
            lbl = pg.TextItem(anchor=(0.0, 0.5))
            # Explicit family: the default/empty-family font lacks the Greek
            # σ glyph and silently drops it (label showed "+0.5", not "+0.5σ").
            lbl.setFont(QtGui.QFont("Arial", 8))
            vb.addItem(lbl, ignoreBounds=True)
            self._sigma_labels.append(lbl)

        for i, lbl in enumerate(self._sigma_labels):
            if i >= len(entries):
                lbl.hide()
                continue
            text, y = entries[i]
            lbl.setColor(WHITE_COLOR)
            lbl.setText(text)
            # Placed one column right of the value labels (which sit at +0.6).
            lbl.setPos(last_ix + 1.6, y)
            lbl.show()

    def _update_roll_labels(self) -> None:
        """Annotate visible strike-roll bars with a "prev|now" strike label."""
        vb = self.getViewBox()
        if vb is None or not self.show_strike_roll or not self.eris_p_iv:
            for lbl in self._roll_labels:
                lbl.hide()
            return

        # Only label roll bars currently in view (keeps the item count bounded).
        (x0, x1), _ = vb.viewRange()
        last_ix: int = max(self.eris_p_iv.keys())
        min_ix: int = max(1, int(x0))
        max_ix: int = min(last_ix, int(x1) + 1)

        # (value map, strike map, colour) per drawn series.
        specs: list[tuple[Dict[int, float], Dict[int, int], tuple]] = [
            (self.eris_p_iv, self.eris_p_strike, DOWN_COLOR),
            (self.eris_c_iv, self.eris_c_strike, RED_COLOR),
            (self.atm_iv, self.eris_a_strike, WHITE_COLOR),
        ]
        if self.show_delta002:
            specs += [
                (self.delta002_p_iv, self.delta002_p_strike, BLUE_COLOR),
                (self.delta002_c_iv, self.delta002_c_strike, YELLOW_COLOR),
            ]

        # Collect (ix, value, colour, prev_strike, now_strike) for roll bars.
        entries: list[tuple[int, float, tuple, int, int]] = []
        for value_map, strike_map, color in specs:
            for ix in range(min_ix, max_ix + 1):
                s_now = strike_map.get(ix)
                s_prev = strike_map.get(ix - 1)
                if s_now is None or s_prev is None or s_now == s_prev:
                    continue
                val = value_map.get(ix)
                if val is None:
                    continue
                entries.append((ix, val, color, int(s_prev), int(s_now)))

        # Grow the pool as needed, then set / hide each label.
        while len(self._roll_labels) < len(entries):
            lbl = pg.TextItem(anchor=(0.5, 1.0))
            lbl.setFont(QtGui.QFont("", 7))
            vb.addItem(lbl, ignoreBounds=True)
            self._roll_labels.append(lbl)

        for i, lbl in enumerate(self._roll_labels):
            if i < len(entries):
                ix, val, color, s_prev, s_now = entries[i]
                lbl.setColor(color)
                # Strikes are in units of 1000 → show 55000|56000 as 55|56
                # ("g" keeps a half-strike like 55500 as 55.5).
                lbl.setText(f"{s_prev / 1000:g}|{s_now / 1000:g}")
                lbl.setPos(ix, val)
                lbl.show()
            else:
                lbl.hide()

    def _update_value_labels(self) -> None:
        """Show each series' latest value as a text label beside its last point."""
        vb = self.getViewBox()
        if vb is None or not self.eris_p_iv:
            return

        last_ix: int = max(self.eris_p_iv.keys())
        # (key, data dict, colour, short tag, visible)
        specs: list[tuple[str, Dict[int, float], tuple, str, bool]] = [
            ("eris_p", self.eris_p_iv, DOWN_COLOR, "P", True),
            ("eris_c", self.eris_c_iv, RED_COLOR, "C", True),
            ("atm", self.atm_iv, WHITE_COLOR, "A", True),
            ("d002_p", self.delta002_p_iv, BLUE_COLOR, "P2", self.show_delta002),
            ("d002_c", self.delta002_c_iv, YELLOW_COLOR, "C2", self.show_delta002),
        ]

        for key, data, color, tag, visible in specs:
            label = self._value_labels.get(key)
            value = data.get(last_ix)
            if not visible or value is None:
                if label is not None:
                    label.hide()
                continue
            if label is None:
                # Anchor (0, 0.5): left-center at the point → text sits to the
                # right of (beside) the latest point.
                label = pg.TextItem(color=color, anchor=(0, 0.5))
                vb.addItem(label, ignoreBounds=True)
                self._value_labels[key] = label
            label.setText(f"{tag}{value:+.2f}")
            # Small gap to the right of the last point so the text does not
            # overlap the latest marker.
            label.setPos(last_ix + 0.6, value)
            label.show()

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

            # Δ0.02 lines only when the toolbar checkbox is enabled.
            words: list = []
            if self.show_delta002:
                words.append(put002)
            words += [put, atm, call]
            if self.show_delta002:
                words.append(call002)

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
