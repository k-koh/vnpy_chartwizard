from typing import Dict, Tuple
import pyqtgraph as pg

from vnpy.chart.item import ChartItem
from vnpy.trader.engine import MainEngine
from vnpy.trader.constant import PriceType, CandleColor, OptionType
from vnpy.trader.ui import QtCore, QtGui
from vnpy.trader.object import BarData
from vnpy.chart.manager import BarManager


class ImpvItem(ChartItem):
    """"""

    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)

        self.bid_pen: QtGui.QPen = pg.mkPen(color=(255, 174, 201), width=2)
        self.ask_pen: QtGui.QPen = pg.mkPen(color=(160, 255, 160), width=2)

        self.option_type = OptionType.CALL
        self.candle_color = CandleColor.YELLOW
        self.iv_data: Dict[int, float] = {}
        self._main_engine: MainEngine = manager.main_engine

        self.base_iv = None

    def get_base_iv(self) -> float | None:
        base_iv = None
        base_bar = self._manager.get_current_session_base_bar()
        if base_bar is not None:
            if self.option_type == OptionType.CALL:
                base_iv = base_bar.eris_c_iv
            else:
                base_iv = base_bar.eris_p_iv
        return base_iv

    def get_impv_value(self, ix: int) -> float:
        """"""
        if ix < 0:
            return 0

        # When initialize, calculate all rsi value
        if not self.iv_data:
            self.base_iv = self.get_base_iv()
            bars = self._manager.get_all_bars()
            for n, bar in enumerate(bars):
                if self.option_type == OptionType.CALL:
                    iv = bar.eris_c_iv
                else:
                    iv = bar.eris_p_iv
                if self.base_iv is None and iv is not None:
                    self.base_iv = iv
                self.iv_data[n] = (iv - self.base_iv) * 100.0 if iv is not None else 0

        new_bar = True if ix not in self.iv_data else False
        update = False
        if self.iv_data:
            update = True if ix == max(self.iv_data.keys()) else False

        if new_bar or update:
            # Else calculate new value
            bar = self._manager.get_bar(ix)
            if self.option_type == OptionType.CALL:
                iv = bar.eris_c_iv
            else:
                iv = bar.eris_p_iv
            if self.base_iv is None and iv is not None:
                self.base_iv = iv
            self.iv_data[ix] = (iv - self.base_iv) * 100.0 if iv is not None else 0

        # Return if already calcualted
        if ix in self.iv_data:
            return self.iv_data[ix]

        return 0

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        impv_value = self.get_impv_value(ix)
        last_impv_value = self.get_impv_value(ix - 1)

        # Create objects
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        # Set painter color
        if self.option_type == OptionType.CALL:
            painter.setPen(self.bid_pen)
        else:
            painter.setPen(self.ask_pen)

        # Draw Line
        start_point = QtCore.QPointF(ix-1, last_impv_value)
        end_point = QtCore.QPointF(ix, impv_value)
        painter.drawLine(start_point, end_point)

        # Finish
        painter.end()
        return picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        # min_price, max_price = self._manager.get_price_range()
        rect = QtCore.QRectF(
            0,
            -2.0,
            len(self._bar_picutures),
            4.0
        )
        return rect

    def get_y_range( self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """  """
        return -2.0, 2.0

    def get_info_text(self, ix: int) -> str:
        """"""
        if ix in self.iv_data:
            impv_value = self.iv_data[ix]
            text = f"Impv {impv_value:.4f}%"
        else:
            text = "Impv -"

        return text

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        self.iv_data.clear()
        super().clear_all()
