from itertools import count
from typing import Dict, Tuple
import pyqtgraph as pg

from vnpy.chart.base import BAR_WIDTH, PEN_WIDTH, to_int
from vnpy.chart.item import ChartItem
from vnpy.trader.constant import PriceType, CandleColor, OptionType
from vnpy.trader.ui import QtCore, QtGui
from vnpy.trader.object import BarData
from vnpy.chart.manager import BarManager

BID_COLOR = (255, 174, 201)
ASK_COLOR = (160, 255, 160)
# ATM_COLOR use yellow
ATM_COLOR = (255, 255, 0)

class IvItem(ChartItem):
    """"""

    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)

        self.bid_pen: QtGui.QPen = pg.mkPen(color=BID_COLOR, width=PEN_WIDTH)
        self.ask_pen: QtGui.QPen = pg.mkPen(color=ASK_COLOR, width=PEN_WIDTH)
        self.atm_pen: QtGui.QPen = pg.mkPen(color=ATM_COLOR, width=PEN_WIDTH)
        self.bid_brush: QtGui.QBrush = pg.mkBrush(color=BID_COLOR)
        self.ask_brush: QtGui.QBrush = pg.mkBrush(color=ASK_COLOR)
        self.atm_brush: QtGui.QBrush = pg.mkBrush(color=ATM_COLOR)

        self.iv_ranges: dict[tuple[int, int], tuple[float, float]] = {}

        # Eris IV data
        self.eris_p_iv: Dict[int, float] = {}
        self.eris_c_iv: Dict[int, float] = {}
        self.atm_iv: Dict[int, float] = {}
        self.n225_vi: Dict[int, float] = {}

        self.base_eris_p_iv = None
        self.base_eris_c_iv = None
        self.base_atm_iv = None
        self.base_n225_vi = None

    def get_base_iv(self):
        base_bar = self._manager.get_current_session_base_bar()
        if base_bar is not None:
            self.base_eris_p_iv = base_bar.eris_p_iv
            self.base_eris_c_iv = base_bar.eris_c_iv
            self.base_atm_iv = base_bar.atm_iv
            self.base_n225_vi = base_bar.n225_vi


    def get_impv_values(self, ix: int) -> tuple[float, float, float, float]:
        """"""
        if ix < 0:
            return 0.0, 0.0, 0.0, 0.0

        # When initialize, calculate all rsi value
        if not self.eris_p_iv:
            self.get_base_iv()
            bars = self._manager.get_all_bars()
            for n, bar in enumerate(bars):
                iv = bar.eris_p_iv
                if self.base_eris_p_iv is None and iv is not None:
                    self.base_eris_p_iv = iv
                self.eris_p_iv[n] = (iv - self.base_eris_p_iv) * 100.0 if iv is not None else 0

                iv = bar.eris_c_iv
                if self.base_eris_c_iv is None and iv is not None:
                    self.base_eris_c_iv = iv
                self.eris_c_iv[n] = (iv - self.base_eris_c_iv) * 100.0 if iv is not None else 0

                iv = bar.atm_iv
                if self.base_atm_iv is None and iv is not None:
                    self.base_atm_iv = iv
                self.atm_iv[n] = (iv - self.base_atm_iv) * 100.0 if iv is not None else 0

        new_bar = True if ix not in self.eris_p_iv else False
        update = False
        if self.eris_p_iv:
            update = True if ix == max(self.eris_p_iv.keys()) else False

        if new_bar or update:
            # Else calculate new value
            bar = self._manager.get_bar(ix)
            iv = bar.eris_p_iv
            if self.base_eris_p_iv is None and iv is not None:
                self.base_eris_p_iv = iv
            self.eris_p_iv[ix] = (iv - self.base_eris_p_iv) * 100.0 if iv is not None else 0

            iv = bar.eris_c_iv
            if self.base_eris_c_iv is None and iv is not None:
                self.base_eris_c_iv = iv
            self.eris_c_iv[ix] = (iv - self.base_eris_c_iv) * 100.0 if iv is not None else 0

            iv = bar.atm_iv
            if self.base_atm_iv is None and iv is not None:
                self.base_atm_iv = iv
            self.atm_iv[ix] = (iv - self.base_atm_iv) * 100.0 if iv is not None else 0

        # Return if already calcualted
        if ix in self.eris_p_iv:
            return self.eris_p_iv[ix], self.eris_c_iv[ix], self.atm_iv[ix], 0.0

        return 0.0, 0.0, 0.0, 0.0

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        # Create objects
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        p_iv, c_iv, atm_iv, n225_vi = self.get_impv_values(ix)
        if abs(p_iv) > abs(c_iv):
            painter.setPen(self.ask_pen)
            painter.setBrush(self.ask_brush)
            rect: QtCore.QRectF = QtCore.QRectF(
                ix - BAR_WIDTH,
                0,
                BAR_WIDTH * 2,
                p_iv
            )
            painter.drawRect(rect)

            painter.setPen(self.bid_pen)
            painter.setBrush(self.bid_brush)
            rect: QtCore.QRectF = QtCore.QRectF(
                ix - BAR_WIDTH,
                0,
                BAR_WIDTH * 2,
                c_iv
            )
            painter.drawRect(rect)
        else:
            painter.setPen(self.bid_pen)
            painter.setBrush(self.bid_brush)
            rect: QtCore.QRectF = QtCore.QRectF(
                ix - BAR_WIDTH,
                0,
                BAR_WIDTH * 2,
                c_iv
            )
            painter.drawRect(rect)

            painter.setPen(self.ask_pen)
            painter.setBrush(self.ask_brush)
            rect: QtCore.QRectF = QtCore.QRectF(
                ix - BAR_WIDTH,
                0,
                BAR_WIDTH * 2,
                p_iv
            )
            painter.drawRect(rect)

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
        return min_iv, max_iv

    def get_iv_range(self, min_ix: float | None = None, max_ix: float | None = None) -> tuple[float, float]:
        """
        Get iv range to show within given index range.
        """
        if not self.eris_p_iv:
            return -1.0, 1.0

        cnt = len(self.eris_p_iv)
        if min_ix is None or max_ix is None:
            min_ix = 0
            max_ix = cnt - 1
        else:
            min_ix = to_int(min_ix)
            max_ix = to_int(max_ix)
            max_ix = min(max_ix, cnt - 1)

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

        min_iv = min(p_iv_min, c_iv_min, atm_iv_min)
        max_iv = max(p_iv_max, c_iv_max, atm_iv_max)

        self.iv_ranges[(min_ix, max_ix)] = (min_iv, max_iv)
        return min_iv, max_iv

    def get_info_text(self, ix: int) -> str:
        """"""
        if ix in self.eris_p_iv:
            a_iv = self.atm_iv[ix]
            p_iv = self.eris_p_iv[ix]
            c_iv = self.eris_c_iv[ix]
            text = f"IV ATM {a_iv:.2f}% OTM-P {p_iv:.2f}% OTM-C {c_iv:.2f}%"
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
