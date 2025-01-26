from typing import Dict, Tuple, List
import numpy as np
import talib
import pyqtgraph as pg

from vnpy.chart.item import ChartItem
from vnpy.trader.ui import QtCore, QtGui
from vnpy.trader.object import BarData
from vnpy.chart.manager import BarManager


from datetime import datetime
from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.database import get_database
from vnpy.chart import ChartWidget, VolumeItem, CandleItem
from vnpy.trader.ui import create_qapp

# Volatility Quality Index indicator

class VqiItem(ChartItem):
    """"""

    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)

        self.aqua_pen: QtGui.QPen = pg.mkPen(color=(0, 255, 255), width=1)
        self.red_pen: QtGui.QPen  = pg.mkPen(color=(255, 0, 0), width=1)

        self.currency_point = 1
        self.vqi_ma_method  = 3 # 3 = MODE_LWMA
        self.vqi_period     = 5
        self.vqi_smoothing  = 2
        self.vqi_filter     = 1
        self.vqi_data: Dict[int, float] = {}
        self.vqi_start      = self.vqi_smoothing + self.vqi_period + 3

    def get_vqi_value(self, ix: int) -> float:
        """"""
        # Return default value when no enough MA and smoothing data
        if ix < self.vqi_start:
            return 0

        # When initialize, calculate all vqi value
        if not self.vqi_data:
            base_ix = 0
            bars = self._manager.get_all_bars()
            open_data  = [bar.open_price  for bar in bars]
            high_data  = [bar.high_price  for bar in bars]
            low_data   = [bar.low_price   for bar in bars]
            close_data = [bar.close_price for bar in bars]
            # initialize VQ with 0
            self.vqi_data = {n: 0.0 for n in range(len(bars))}
            self.caculate_vqi(open_data, high_data, low_data, close_data, base_ix)

        # Calculate new value
        # and Recalculate current bar
        max_key = max(self.vqi_data.keys())
        if ix not in self.vqi_data or ix == max_key:
            open_data = []
            high_data = []
            low_data = []
            close_data = []
            # -1 for update previous fixed bar
            base_ix = ix - self.vqi_start - 1
            for n in range(base_ix, ix + 1):
                bar = self._manager.get_bar(n)
                open_data.append(bar.open_price)
                high_data.append(bar.high_price)
                low_data.append(bar.low_price)
                close_data.append(bar.close_price)
            self.caculate_vqi(open_data, high_data, low_data, close_data, base_ix)

        if ix in self.vqi_data:
            return self.vqi_data[ix]


    def caculate_vqi(self, open_data: list, high_data: list, low_data: list, close_data: list, base_ix: int = 0):
        """"""
        maO_array = talib.MA(np.array(open_data),  timeperiod=self.vqi_period, matype=self.vqi_ma_method)
        maH_array = talib.MA(np.array(high_data),  timeperiod=self.vqi_period, matype=self.vqi_ma_method)
        maL_array = talib.MA(np.array(low_data),   timeperiod=self.vqi_period, matype=self.vqi_ma_method)
        maC_array = talib.MA(np.array(close_data), timeperiod=self.vqi_period, matype=self.vqi_ma_method)

        count = len(maO_array)
        # loop index [start, total - 1]
        for i in range(self.vqi_start, count):
            # calculate VQI
            o = maO_array[i]
            h = maH_array[i]
            l = maL_array[i]
            c = maC_array[i]
            c2 = maC_array[i - self.vqi_smoothing]
            max_p = max(h - l, max(h - c2, c2 - l))
            if (max_p != 0 and (h - l) != 0):
                VQ = abs(((c-c2)/max_p+(c-o)/(h-l))*0.5)*((c-c2+(c-o))*0.5)
                self.vqi_data[base_ix+i] = self.vqi_data[base_ix+i-1] if abs(VQ) < self.vqi_filter * self.currency_point else VQ


    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        vqi_value = self.get_vqi_value(ix)

        # Create objects
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        if vqi_value > 0:
            painter.setPen(self.red_pen)
        else:
            painter.setPen(self.aqua_pen)

        # Draw VQI rectangle
        painter.drawRect(
            QtCore.QRectF(
                ix - 0.4, # 0.4 = 0.8(width) / 2
                50,       # 50% of y_range
                0.8,      # width
                20        # 20% of y_range
            )
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
        if ix in self.vqi_data:
            rsi_value = self.vqi_data[ix]
            text = f"VQI {rsi_value:.1f}"
            # print(text)
        else:
            text = "VQI -"

        return text


if __name__ == "__main__":
    app = create_qapp()

    symbol = "JP225"
    exchange = Exchange.OTC
    interval = Interval.MINUTE
    start = datetime(2025, 1, 23, 22, 15, 0),
    end   = datetime(2025, 1, 25, 22, 15, 0)

    database = get_database()
    bars = database.load_bar_data(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        start=start,
        end=end
    )

    n = 1000
    history = bars[:n]
    new_data = bars[n:]

    widget = ChartWidget()
    widget.add_plot("candle", hide_x_axis=True)
    widget.add_plot("volume", maximum_height=250)
    widget.add_plot("vqi", maximum_height=150)

    widget.add_item(CandleItem, "candle", "candle")
    widget.add_item(VolumeItem, "volume", "volume")
    widget.add_item(VqiItem, "vqi", "vqi")
    widget.add_cursor()

    # history = bars
    widget.update_history(history)

    def update_bar():
        bar = new_data.pop(0)
        widget.update_bar(bar)

    timer = QtCore.QTimer()
    timer.timeout.connect(update_bar)
    # timer.start(100)

    widget.show()
    app.exec()
