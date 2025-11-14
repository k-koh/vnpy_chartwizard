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

        self.yellow_pen: QtGui.QPen = pg.mkPen(color=(255, 255, 0), width=2)
        self.magenta_pen: QtGui.QPen = pg.mkPen(color=(255, 0, 255), width=2)

        self.option_type = OptionType.CALL
        self.candle_color = CandleColor.YELLOW
        self.impv_data: Dict[int, float] = {}
        self._main_engine: MainEngine = manager.main_engine

        self.init_impv = None

    def get_impv_value(self, ix: int) -> float:
        """"""
        if ix < 0:
            return 0

        # When initialize, calculate all rsi value
        if not self.impv_data:
            bars = self._manager.get_all_bars()

        new_bar = True if ix not in self.impv_data else False
        update = False
        if self.impv_data:
            update = True if ix == max(self.impv_data.keys()) else False

        if new_bar or update:
            # Else calculate new value
            impv_value = 0
            gateway = self._main_engine.get_gateway("KBS")
            if gateway:
                option_engine = self._main_engine.get_engine("OptionMaster")
                if option_engine:
                    if self.option_type == OptionType.CALL:
                        eris_match = gateway.rest_api.eris_call_match
                    else:
                        eris_match = gateway.rest_api.eris_put_match
                    
                    kabus_symbol = eris_match.get('symbol')
                    if kabus_symbol:
                        option_data = option_engine.get_option_data_by_kabus_symbol(kabus_symbol)
                        if option_data and option_data.mid_impv:
                            impv_value = option_data.mid_impv
                        else:
                            # Fallback to impv from Kabus API if OptionMaster data is not available
                            impv_value = eris_match.get('impv', 0)
                else:
                    # Fallback to impv from Kabus API if OptionMaster engine is not available
                    if self.option_type == OptionType.CALL:
                        eris_match = gateway.rest_api.eris_call_match
                    else:
                        eris_match = gateway.rest_api.eris_put_match
                    impv_value = eris_match.get('impv', 0)
            else:
                # Fallback to 0 if gateway is not available
                impv_value = 0
            
            if impv_value is None: # Ensure it's a float
                impv_value = 0

            if self.init_impv is None:
                self.init_impv = impv_value

            self.impv_data[ix] = (impv_value - self.init_impv) * 100.0

        # Return if already calcualted
        if ix in self.impv_data:
            return self.impv_data[ix]

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
            painter.setPen(self.magenta_pen)
        else:
            painter.setPen(self.yellow_pen)

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
            -3.0,
            len(self._bar_picutures),
            6.0
        )
        return rect

    def get_y_range( self, min_ix: int = None, max_ix: int = None) -> Tuple[float, float]:
        """  """
        return -3.0, 3.0

    def get_info_text(self, ix: int) -> str:
        """"""
        if ix in self.impv_data:
            impv_value = self.impv_data[ix]
            text = f"Impv {impv_value:.4f}%"
        else:
            text = "Impv -"

        return text

    def clear_all(self) -> None:
        """
        Clear all data in the item.
        """
        self.impv_data.clear()
        super().clear_all()
