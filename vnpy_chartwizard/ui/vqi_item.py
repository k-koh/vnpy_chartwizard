from typing import Dict, Tuple
import talib
import pyqtgraph as pg
from vnpy.chart.item import ChartItem
from vnpy.trader.ui import QtCore, QtGui
from vnpy.trader.object import BarData
from vnpy.chart.manager import BarManager
from vnpy.trader.utility import ArrayManager

# Volatility Quality Index indicator

class VqiItem(ChartItem):
    """"""

    def __init__(self, manager: BarManager):
        """"""
        super().__init__(manager)
        self.am = ArrayManager()

        self.aqua_pen: QtGui.QPen     = pg.mkPen(color=(0, 255, 255), width=1)
        self.red_pen: QtGui.QPen      = pg.mkPen(color=(255, 0, 0), width=1)
        self.fill_color: QtGui.QColor = pg.mkColor(0, 0, 0, 255)

        self.currency_point = 1
        self.vqi_ma_method  = 3 # 3 = MODE_LWMA
        self.vqi_period     = 5
        self.vqi_smoothing  = 2
        self.vqi_filter     = 1
        self.vqi_data: Dict[int, float] = {}
        self.pre_vqi        = 0.0

    def get_vqi_value(self, ix: int) -> float:
        """"""
        am = self.am
        # Return default value when no enough ArrayManager data (size=100)
        if ix < am.size-1:
            return 0.0
        # When initialize, calculate all vqi value
        if not self.vqi_data:
            bars = self._manager.get_all_bars()
            for bar in bars:
                am.update_bar(bar)
                if not am.inited:
                    continue
                idx = self._manager.get_index(bar.datetime)
                self.vqi_data[idx] = self.caculate_vqi()
                self.pre_vqi = self.vqi_data[idx]
        # add a new bar or update the last bar
        new_bar = True if ix not in self.vqi_data else False
        update = True if ix == max(self.vqi_data.keys()) else False
        if new_bar or update:
            am.update_bar(self._manager.get_bar(ix), new_bar)
            if not am.inited:
                return 0.0
            self.vqi_data[ix] = self.caculate_vqi()
            self.pre_vqi = self.vqi_data[ix]
        if ix in self.vqi_data:
            return self.vqi_data[ix]

    def caculate_vqi(self) -> float:
        """"""
        maO_array = talib.MA(self.am.open,  timeperiod=self.vqi_period, matype=self.vqi_ma_method)
        maH_array = talib.MA(self.am.high,  timeperiod=self.vqi_period, matype=self.vqi_ma_method)
        maL_array = talib.MA(self.am.low,   timeperiod=self.vqi_period, matype=self.vqi_ma_method)
        maC_array = talib.MA(self.am.close, timeperiod=self.vqi_period, matype=self.vqi_ma_method)
        # calculate VQI
        o = maO_array[-1]
        h = maH_array[-1]
        l = maL_array[-1]
        c = maC_array[-1]
        c2 = maC_array[-1-self.vqi_smoothing]
        max_p = max(h - l, max(h - c2, c2 - l))
        if (max_p != 0 and (h - l) != 0):
            VQ = abs(((c - c2) / max_p + (c - o) / (h - l)) * 0.5) * ((c - c2 + (c - o)) * 0.5)
            vqi = self.pre_vqi if abs(VQ) < self.vqi_filter * self.currency_point else VQ
            return vqi
        else:
            return 0.0

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """"""
        vqi_value = self.get_vqi_value(ix)

        # Create objects
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        rgb = min(255, int(50 * abs(vqi_value)))
        if vqi_value > 0.0:
            painter.setPen(self.red_pen)
            self.fill_color.setRgb(rgb, 0, 0)
        else:
            painter.setPen(self.aqua_pen)
            self.fill_color.setRgb(0, rgb, rgb)

        # Draw VQI rectangle
        rect = QtCore.QRectF(
            ix - 0.4, # 0.4 = 0.8(width) / 2
            50,       # 50% of y_range
            0.8,      # width
            20        # 20% of y_range
        )
        painter.fillRect(rect, self.fill_color)
        painter.drawRect(rect)

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
            text = f"VQI {rsi_value:.5f}"
            # print(text)
        else:
            text = "VQI -"

        return text

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        self.am = ArrayManager()
        self.vqi_data.clear()
        self.pre_vqi = 0.0
        super().clear_all()