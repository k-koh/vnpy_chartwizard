from typing import  Dict
import numpy as np
import talib
from vnpy.chart import CandleItem
import pyqtgraph as pg

from vnpy.trader.constant import PriceType, CandleColor
from vnpy.trader.ui import QtCore, QtGui
from vnpy.trader.object import BarData
from vnpy.chart.manager import BarManager

class SmaItem(CandleItem):
    """"""

    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)

        self.yellow_pen: QtGui.QPen = pg.mkPen(color=(255, 255, 0), width=2)
        self.magenta_pen: QtGui.QPen = pg.mkPen(color=(255, 0, 255), width=2)
        self.orange_pen: QtGui.QPen = pg.mkPen(color=(255, 165, 0), width=2)

        self.sma_window = 20
        self.price_type = PriceType.CLOSE
        self.candle_color = CandleColor.YELLOW
        self.sma_data: Dict[int, float] = {}

    def get_sma_value(self, ix: int) -> float:
        """"""
        if ix < 0:
            return 0

        # When initialize, calculate all rsi value
        if not self.sma_data:
            bars = self._manager.get_all_bars()
            if self.price_type == PriceType.CLOSE:
                close_data = [bar.close_price for bar in bars]
            else:
                close_data = [bar.open_price for bar in bars]
            sma_array = talib.SMA(np.array(close_data), timeperiod=self.sma_window)

            for n, value in enumerate(sma_array):
                self.sma_data[n] = value

        new_bar = True if ix not in self.sma_data else False
        update = True if ix == max(self.sma_data.keys()) else False
        if new_bar or update:
            # Else calculate new value
            close_data = []
            for n in range(ix - self.sma_window, ix + 1):
                bar = self._manager.get_bar(n)
                if self.price_type == PriceType.CLOSE:
                    close_data.append(bar.close_price)
                else:
                    close_data.append(bar.open_price)

            sma_array = talib.SMA(np.array(close_data), timeperiod=self.sma_window)
            sma_value = sma_array[-1]
            self.sma_data[ix] = sma_value

        # Return if already calcualted
        if ix in self.sma_data:
            return self.sma_data[ix]

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        sma_value = self.get_sma_value(ix)
        last_sma_value = self.get_sma_value(ix - 1)

        # Create objects
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        # Set painter color
        if self.candle_color == CandleColor.MAGENTA:
            painter.setPen(self.magenta_pen)
        elif self.candle_color == CandleColor.ORANGE:
            painter.setPen(self.orange_pen)
        else:
            painter.setPen(self.yellow_pen)

        # Draw Line
        start_point = QtCore.QPointF(ix-1, last_sma_value)
        end_point = QtCore.QPointF(ix, sma_value)
        painter.drawLine(start_point, end_point)

        # Finish
        painter.end()
        return picture

    def get_info_text(self, ix: int) -> str:
        """"""
        if ix in self.sma_data:
            sma_value = self.sma_data[ix]
            text = f"SMA {sma_value:.1f}"
        else:
            text = "SMA -"

        return text

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        self.sma_data.clear()
        super().clear_all()
