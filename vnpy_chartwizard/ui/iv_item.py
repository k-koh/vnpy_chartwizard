from datetime import datetime
from itertools import count
from typing import Dict, Tuple
from dataclasses import dataclass
import pyqtgraph as pg

from vnpy.chart.base import BAR_WIDTH, PEN_WIDTH, to_int, DOWN_COLOR, UP_COLOR, ATM_COLOR
from vnpy.chart.item import ChartItem
from vnpy.trader.constant import PriceType, CandleColor, OptionType, OptionPrevIvType
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

        self.bid_pen: QtGui.QPen = pg.mkPen(color=UP_COLOR, width=PEN_WIDTH)
        self.ask_pen: QtGui.QPen = pg.mkPen(color=DOWN_COLOR, width=PEN_WIDTH)
        self.atm_pen: QtGui.QPen = pg.mkPen(color=ATM_COLOR, width=PEN_WIDTH)
        self.atm_range1x_pen: QtGui.QPen = pg.mkPen(color=ATM_COLOR, width=PEN_WIDTH)
        self.atm_range1x_pen.setStyle(QtCore.Qt.DashLine)
        self.atm_range2x_pen: QtGui.QPen = pg.mkPen(color=ATM_COLOR, width=PEN_WIDTH)
        self.atm_range2x_pen.setStyle(QtCore.Qt.DashLine)
        self.bid_brush: QtGui.QBrush = pg.mkBrush(color=UP_COLOR)
        self.ask_brush: QtGui.QBrush = pg.mkBrush(color=DOWN_COLOR)
        self.atm_brush: QtGui.QBrush = pg.mkBrush(color=ATM_COLOR)

        self.iv_ranges: dict[tuple[int, int], tuple[float, float]] = {}

        self.prev_iv_type: OptionPrevIvType = OptionPrevIvType.SAME_STRIKE

        # Eris IV data
        self.eris_p_strike: Dict[int, int] = {}
        self.eris_c_strike: Dict[int, int] = {}
        self.eris_a_strike: Dict[int, int] = {}
        self.eris_p_iv: Dict[int, float] = {}
        self.eris_c_iv: Dict[int, float] = {}
        self.atm_iv: Dict[int, float] = {}
        self.n225_vi: Dict[int, float] = {}
        # atm_iv 年率から日率に変換
        self.atm_iv_daily: Dict[int, float] = {}


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


    def get_impv_values(self, ix: int) -> tuple[float, float, float, float]:
        """"""
        if ix < 0:
            return 0.0, 0.0, 0.0, 0.0

        # When initialize, calculate all rsi value
        if not self.eris_p_iv:
            dt: datetime = datetime.now(DB_TZ)
            bars = self._manager.get_all_bars()
            for n, bar in enumerate(bars):
                # find 2025-11-20 03:39:00 bar to test
                # if bar.datetime == datetime(2025, 11, 20, 22, 30, 0, tzinfo=bar.datetime.tzinfo):
                #     print("debug it")
                atm_price = round(bar.close_price / 500) * 500
                prev_p_iv, prev_c_iv, prev_a_iv = self.get_prev_day_option_iv(
                    bar.vt_symbol,
                    self.prev_iv_type,
                    bar.eris_p_strike,
                    bar.eris_c_strike,
                    atm_price,
                    dt
                )
                iv = bar.eris_p_iv
                self.eris_p_iv[n] = (iv - prev_p_iv) * 100.0 if iv is not None and iv != 0 and prev_p_iv != 0 else 0
                self.eris_p_strike[n] = bar.eris_p_strike

                iv = bar.eris_c_iv
                self.eris_c_iv[n] = (iv - prev_c_iv) * 100.0 if iv is not None and iv != 0 and prev_c_iv != 0 else 0
                self.eris_c_strike[n] = bar.eris_c_strike

                iv = bar.atm_iv
                self.atm_iv[n] = (iv - prev_a_iv) * 100.0 if iv is not None and iv != 0 and prev_a_iv != 0 else 0
                self.eris_a_strike[n] = atm_price
                # atm_iv 年率から日率に変換
                self.atm_iv_daily[n] = iv * 100.0 / (252 ** 0.5) if iv is not None and iv != 0 else 0

        new_bar = True if ix not in self.eris_p_iv else False
        update = False
        if self.eris_p_iv:
            update = True if ix == max(self.eris_p_iv.keys()) else False

        if new_bar or update:
            # Else calculate new value
            bar = self._manager.get_bar(ix)
            # find 2025-11-20 03:39:00 bar to test
            # if bar.datetime == datetime(2025, 11, 20, 22, 30, 0, tzinfo=bar.datetime.tzinfo):
            #     print("debug it")
            atm_price = round(bar.close_price / 500) * 500
            dt: datetime = datetime.now(DB_TZ)
            prev_p_iv, prev_c_iv, prev_a_iv = self.get_prev_day_option_iv(
                bar.vt_symbol,
                self.prev_iv_type,
                bar.eris_p_strike,
                bar.eris_c_strike,
                atm_price,
                dt
            )
            iv = bar.eris_p_iv
            self.eris_p_iv[ix] = (iv - prev_p_iv) * 100.0 if iv is not None and iv != 0 and prev_p_iv != 0 else 0
            self.eris_p_strike[ix] = bar.eris_p_strike

            iv = bar.eris_c_iv
            self.eris_c_iv[ix] = (iv - prev_c_iv) * 100.0 if iv is not None and iv != 0 and prev_c_iv != 0 else 0
            self.eris_c_strike[ix] = bar.eris_c_strike

            iv = bar.atm_iv
            self.atm_iv[ix] = (iv - prev_a_iv) * 100.0 if iv is not None and iv != 0 and prev_a_iv != 0 else 0
            self.eris_a_strike[ix] = atm_price
            # atm_iv 年率から日率に変換
            self.atm_iv_daily[ix] = iv * 100.0 / (252 ** 0.5) if iv is not None and iv != 0 else 0

        # Return if already calcualted
        if ix in self.eris_p_iv:
            return self.eris_p_iv[ix], self.eris_c_iv[ix], self.atm_iv[ix], self.atm_iv_daily[ix]

        return 0.0, 0.0, 0.0, 0.0

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        # Create objects
        p_iv, c_iv, atm_iv, atm_iv_daily = self.get_impv_values(ix)

        draw_items = [
            IvDrawItem(value=p_iv, pen=self.ask_pen, brush=self.ask_brush),
            IvDrawItem(value=c_iv, pen=self.bid_pen, brush=self.bid_brush),
            IvDrawItem(value=atm_iv, pen=self.atm_pen, brush=self.atm_brush),
        ]

        draw_items.sort(key=lambda item: abs(item.value), reverse=True)

        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

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

        # ATM daily upper line
        painter.setPen(self.atm_range1x_pen)
        start_point = QtCore.QPointF(ix - BAR_WIDTH, atm_iv_daily)
        end_point = QtCore.QPointF(ix + BAR_WIDTH, atm_iv_daily)
        painter.drawLine(start_point, end_point)

        # ATM daily lower line
        start_point = QtCore.QPointF(ix - BAR_WIDTH, -atm_iv_daily)
        end_point = QtCore.QPointF(ix + BAR_WIDTH, -atm_iv_daily)
        painter.drawLine(start_point, end_point)

        max_iv = max(abs(atm_iv), abs(p_iv), abs(c_iv))
        if max_iv > atm_iv_daily * 1.5:
            # ATM daily dashed line
            painter.setPen(self.atm_range2x_pen)

            # upper line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, atm_iv_daily * 2.0)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, atm_iv_daily * 2.0)
            painter.drawLine(start_point, end_point)

            # lower line
            start_point = QtCore.QPointF(ix - BAR_WIDTH, -atm_iv_daily * 2.0)
            end_point = QtCore.QPointF(ix + BAR_WIDTH, -atm_iv_daily * 2.0)
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

        atm_iv_values = list(self.atm_iv.values())[min_ix:max_ix + 1]
        atm_iv_min = min(atm_iv_values)
        atm_iv_max = max(atm_iv_values)

        atm_iv_daily_values = list(self.atm_iv_daily.values())[min_ix:max_ix + 1]
        atm_iv_daily_max = max(atm_iv_daily_values) # atm_iv_daily upper line
        atm_iv_daily_min = -atm_iv_daily_max        # atm_iv_daily lower line

        min_iv = min(p_iv_min, c_iv_min, atm_iv_min, atm_iv_daily_min)
        max_iv = max(p_iv_max, c_iv_max, atm_iv_max, atm_iv_daily_max)

        if min_iv < atm_iv_daily_min * 1.5:
            min_iv = min(min_iv, atm_iv_daily_min * 2.0)
        if max_iv > atm_iv_daily_max * 1.5:
            max_iv = max(max_iv, atm_iv_daily_max * 2.0)

        self.iv_ranges[(min_ix, max_ix)] = (min_iv, max_iv)
        return min_iv, max_iv

    def get_info_text(self, ix: int) -> str:
        """"""
        if ix in self.eris_p_iv:
            a_strike = self.eris_a_strike[ix]
            p_strike = self.eris_p_strike[ix]
            c_strike = self.eris_c_strike[ix]
            a_iv = self.atm_iv[ix]
            p_iv = self.eris_p_iv[ix]
            c_iv = self.eris_c_iv[ix]
            text = f"前日比OTM IV({self.prev_iv_type.value}) ATM({a_strike}) {a_iv:.2f}% PUT({p_strike}) {p_iv:.2f}% CALL({c_strike}) {c_iv:.2f}%"
        else:
            text = "IV -"

        return text

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        self.eris_p_iv.clear()
        self.eris_c_iv.clear()
        self.atm_iv.clear()
        self.iv_ranges.clear()
        super().clear_all()
