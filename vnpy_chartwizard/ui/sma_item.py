from typing import  Dict
import numpy as np
import talib
from vnpy.chart import CandleItem
import pyqtgraph as pg
from vnpy.trader.ui import QtCore, QtGui
from vnpy.trader.object import BarData
from vnpy.chart.manager import BarManager

class SmaItem(CandleItem):
    """"""

    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)

        self.blue_pen: QtGui.QPen = pg.mkPen(color=(100, 100, 255), width=2)

        self.sma_window = 20
        self.sma_data: Dict[int, float] = {}

    def get_sma_value(self, ix: int) -> float:
        """"""
        if ix < 0:
            return 0

        # When initialize, calculate all rsi value
        if not self.sma_data:
            bars = self._manager.get_all_bars()
            close_data = [bar.close_price for bar in bars]
            sma_array = talib.SMA(np.array(close_data), timeperiod=self.sma_window)

            for n, value in enumerate(sma_array):
                self.sma_data[n] = value

        # Return if already calcualted
        if ix in self.sma_data:
            return self.sma_data[ix]

        # Else calculate new value
        close_data = []
        for n in range(ix - self.sma_window, ix + 1):
            bar = self._manager.get_bar(n)
            close_data.append(bar.close_price)

        sma_array = talib.SMA(np.array(close_data), timeperiod=self.sma_window)
        sma_value = sma_array[-1]
        self.sma_data[ix] = sma_value

        return sma_value

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        sma_value = self.get_sma_value(ix)
        last_sma_value = self.get_sma_value(ix - 1)

        # Create objects
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        # Set painter color
        painter.setPen(self.blue_pen)

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
