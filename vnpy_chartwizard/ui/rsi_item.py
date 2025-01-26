from typing import Dict, Tuple
import numpy as np
import talib
import pyqtgraph as pg

from vnpy.chart.item import ChartItem
from vnpy.trader.ui import QtCore, QtGui
from vnpy.trader.object import BarData
from vnpy.chart.manager import BarManager


class RsiItem(ChartItem):
    """"""

    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)

        self.white_pen: QtGui.QPen = pg.mkPen(color=(255, 255, 255), width=1)
        self.yellow_pen: QtGui.QPen = pg.mkPen(color=(255, 255, 0), width=2)

        self.rsi_window = 14
        self.rsi_data: Dict[int, float] = {}

    def get_rsi_value(self, ix: int) -> float:
        """"""
        if ix < self.rsi_window:
            return 50

        # When initialize, calculate all rsi value
        if not self.rsi_data:
            bars = self._manager.get_all_bars()
            close_data = [bar.close_price for bar in bars]
            rsi_array = talib.RSI(np.array(close_data), timeperiod=self.rsi_window)

            for n, value in enumerate(rsi_array):
                self.rsi_data[n] = value

        # Return if already calcualted
        if ix in self.rsi_data:
            return self.rsi_data[ix]

        # Else calculate new value
        close_data = []
        for n in range(ix - self.rsi_window, ix + 1):
            bar = self._manager.get_bar(n)
            close_data.append(bar.close_price)

        rsi_array = talib.RSI(np.array(close_data), timeperiod=self.rsi_window)
        rsi_value = rsi_array[-1]
        self.rsi_data[ix] = rsi_value

        return rsi_value

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        rsi_value = self.get_rsi_value(ix)
        last_rsi_value = self.get_rsi_value(ix - 1)

        # Create objects
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        # Draw RSI line
        painter.setPen(self.yellow_pen)

        if np.isnan(last_rsi_value) or np.isnan(rsi_value):
            # print(ix - 1, last_rsi_value,ix, rsi_value,)
            pass
        else:
            end_point = QtCore.QPointF(ix, rsi_value)
            start_point = QtCore.QPointF(ix - 1, last_rsi_value)
            painter.drawLine(start_point, end_point)

        # Draw oversold/overbought line
        painter.setPen(self.white_pen)

        painter.drawLine(
            QtCore.QPointF(ix, 70),
            QtCore.QPointF(ix - 1, 70),
        )

        painter.drawLine(
            QtCore.QPointF(ix, 30),
            QtCore.QPointF(ix - 1, 30),
        )

        # Finish
        painter.end()
        return picture

    def boundingRect(self) -> QtCore.QRectF:
        """"""
        # min_price, max_price = self._manager.get_price_range()
        rect = QtCore.QRectF(
            0,
            0,
            len(self._bar_picutures),
            100
        )
        return rect

    def get_y_range( self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """  """
        return 0, 100

    def get_info_text(self, ix: int) -> str:
        """"""
        if ix in self.rsi_data:
            rsi_value = self.rsi_data[ix]
            text = f"RSI {rsi_value:.1f}"
            # print(text)
        else:
            text = "RSI -"

        return text
