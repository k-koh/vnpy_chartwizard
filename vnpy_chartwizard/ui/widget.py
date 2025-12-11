from copy import copy
from datetime import datetime, timedelta
from tzlocal import get_localzone_name

import pyqtgraph as pg

from vnpy.trader.constant import PriceType, CandleColor, OptionType, OptionPrevIvType
from vnpy.event import EventEngine, Event
from vnpy.chart import ChartWidget, CandleItem, VolumeItem
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import QtWidgets, QtCore
from vnpy.trader.event import EVENT_TICK
from vnpy.trader.object import ContractData, TickData, BarData, SubscribeRequest
from vnpy.trader.utility import BarGenerator, ZoneInfo
from vnpy.trader.constant import Interval, Exchange
from vnpy_spreadtrading.base import SpreadItem, EVENT_SPREAD_DATA

from .rsi_item import RsiItem
from .sma_item import SmaItem
from .vqi_item import VqiItem
from .iv_item import IvItem
from ..engine import APP_NAME, EVENT_CHART_HISTORY, ChartWizardEngine

class CustomChartWidget(ChartWidget):
    """
    Custom ChartWidget that holds a reference to main_engine.
    """
    def __init__(self, main_engine: MainEngine) -> None:
        super().__init__()
        self._manager.main_engine = main_engine


class ChartWizardWidget(QtWidgets.QWidget):
    """K线图表控件"""

    signal_tick: QtCore.Signal = QtCore.Signal(Event)
    signal_spread: QtCore.Signal = QtCore.Signal(Event)
    signal_history: QtCore.Signal = QtCore.Signal(Event)

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine) -> None:
        """构造函数"""
        super().__init__()

        self.main_engine: MainEngine = main_engine
        self.event_engine: EventEngine = event_engine
        self.chart_engine: ChartWizardEngine = main_engine.get_engine(APP_NAME)

        self.bgs: dict[str, BarGenerator] = {}
        self.charts: dict[str, ChartWidget] = {}
        # set bar window size same with query_history()
        self.bar_window = 1 # need to change for other timeframes(5m, 15m, 1h, 1d)

        self.history_inited = False
        self.init_ui()
        self.register_event()

    def init_ui(self) -> None:
        """初始化界面"""
        self.setWindowTitle("株価チャート")

        self.tab: QtWidgets.QTabWidget = QtWidgets.QTabWidget()

        self.tab.setTabsClosable(True)
        self.tab.tabCloseRequested.connect(self.close_tab)

        self.symbol_line: QtWidgets.QComboBox = QtWidgets.QComboBox()
        self.symbol_line.addItems(["nk-2512.JPX", "nk-2601.JPX"])

        self.button: QtWidgets.QPushButton = QtWidgets.QPushButton("新規チャート")
        self.button.clicked.connect(self.new_chart)

        hbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox.addWidget(QtWidgets.QLabel("銘柄コード"))
        hbox.addWidget(self.symbol_line)
        hbox.addWidget(self.button)
        hbox.addStretch()

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addLayout(hbox)
        vbox.addWidget(self.tab)

        self.setLayout(vbox)

    def create_chart(self) -> ChartWidget:
        """创建图表对象"""
        chart: ChartWidget = CustomChartWidget(self.main_engine)
        chart.add_plot("candle", hide_x_axis=True)
        # chart.add_plot("otm_delta_iv", maximum_height=400, hide_x_axis=True)
        chart.add_plot("otm_strike_iv", maximum_height=400, hide_x_axis=True)
        chart.add_plot("volume", maximum_height=200)

        chart.add_item(CandleItem, "candle", "candle")
        # chart.add_item(IvItem, "otm_delta_iv", "otm_delta_iv")
        chart.add_item(IvItem, "otm_strike_iv", "otm_strike_iv")
        chart.add_item(VolumeItem, "volume", "volume")

        # set IvItem prev iv type
        # chart._items["otm_delta_iv"].prev_iv_type = OptionPrevIvType.SAME_DELTA
        chart._items["otm_strike_iv"].prev_iv_type = OptionPrevIvType.SAME_STRIKE

        chart.add_cursor()
        return chart

    def show(self) -> None:
        """最大化显示"""
        self.showMaximized()

    def close_tab(self, index: int) -> None:
        """关闭标签"""
        vt_symbol: str = self.tab.tabText(index)

        self.tab.removeTab(index)
        self.charts.pop(vt_symbol)
        self.bgs.pop(vt_symbol)

    def new_chart(self) -> None:
        """创建新的图表"""
        # Filter invalid vt_symbol
        vt_symbol: str = self.symbol_line.currentText()
        if not vt_symbol:
            return

        if vt_symbol in self.charts:
            return

        if "LOCAL" not in vt_symbol:
            contract: ContractData | None = self.main_engine.get_contract(vt_symbol)
            if not contract:
                return

        # Create new chart
        self.bgs[vt_symbol] = BarGenerator(self.on_bar, self.bar_window, self.on_10min_bar)
        self.bgs[vt_symbol].main_engine = self.main_engine

        chart: ChartWidget = self.create_chart()
        self.charts[vt_symbol] = chart

        self.tab.addTab(chart, vt_symbol)

        # Query history data
        end: datetime = datetime.now(ZoneInfo(get_localzone_name()))
        start: datetime = end - timedelta(days=14)

        self.chart_engine.query_history(
            vt_symbol,
            Interval.MINUTE,
            start,
            end
        )

    def register_event(self) -> None:
        """注册事件监听"""
        self.signal_tick.connect(self.process_tick_event)
        self.signal_history.connect(self.process_history_event)
        self.signal_spread.connect(self.process_spread_event)

        self.event_engine.register(EVENT_CHART_HISTORY, self.signal_history.emit)
        self.event_engine.register(EVENT_TICK, self.signal_tick.emit)
        self.event_engine.register(EVENT_SPREAD_DATA, self.signal_spread.emit)

    def process_tick_event(self, event: Event) -> None:
        """处理Tick事件"""
        tick: TickData = event.data
        bg: BarGenerator | None = self.bgs.get(tick.vt_symbol, None)

        if bg and self.history_inited:
            bg.update_tick(tick)

            chart: ChartWidget = self.charts[tick.vt_symbol]
            bar: BarData = None
            if self.bar_window > 0:
                # Update 1 minute bar into x minute window
                bar = copy(bg.bar)
                bg.update_bar(bar)
                bar = copy(bg.window_bar)
            else:
                bar = copy(bg.bar)
            bar.datetime = bar.datetime.replace(second=0, microsecond=0)
            chart.update_bar(bar)

    def process_history_event(self, event: Event) -> None:
        """处理历史事件"""
        history: list[BarData] = event.data
        if not history:
            return

        bar: BarData = history[0]
        chart: ChartWidget = self.charts[bar.vt_symbol]
        chart.update_history(history)

        # update last bar into x minute window
        bar = history[-1]
        bg: Optional[BarGenerator] = self.bgs.get(bar.vt_symbol, None)
        if bg:
            bg.update_bar(bar)
        self.history_inited = True

        # Subscribe following data update
        contract: ContractData | None = self.main_engine.get_contract(bar.vt_symbol)
        if contract:
            req: SubscribeRequest = SubscribeRequest(
                contract.symbol,
                contract.exchange
            )
            self.main_engine.subscribe(req, contract.gateway_name)

    def process_spread_event(self, event: Event) -> None:
        """处理价差事件"""
        spread_item: SpreadItem = event.data
        tick: TickData = TickData(
            symbol=spread_item.name,
            exchange=Exchange.LOCAL,
            datetime=spread_item.datetime,
            name=spread_item.name,
            last_price=(spread_item.bid_price + spread_item.ask_price) / 2,
            bid_price_1=spread_item.bid_price,
            ask_price_1=spread_item.ask_price,
            bid_volume_1=spread_item.bid_volume,
            ask_volume_1=spread_item.ask_volume,
            gateway_name="SPREAD"
        )

        bg: BarGenerator | None = self.bgs.get(tick.vt_symbol, None)
        if bg:
            bg.update_tick(tick)

            chart: ChartWidget = self.charts[tick.vt_symbol]
            bar: BarData = copy(bg.bar)
            bar.datetime = bar.datetime.replace(second=0, microsecond=0)
            chart.update_bar(bar)

    def on_bar(self, bar: BarData, new_minute: bool = True) -> None:
        """K线合成回调"""
        # chart: ChartWidget = self.charts[bar.vt_symbol]
        # chart.update_bar(bar)
        # self.bg.update_bar(bar)

    def on_10min_bar(self, bar: BarData):
        """"""
        # chart: ChartWidget = self.charts[bar.vt_symbol]
        # chart.update_bar(bar)
