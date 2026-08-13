from copy import copy
from datetime import datetime, time, timedelta
from tzlocal import get_localzone_name

import pyqtgraph as pg

from vnpy.trader.constant import PriceType, CandleColor, OptionType, OptionPrevIvType
from vnpy.event import EventEngine, Event
from vnpy.chart import ChartWidget, CandleItem, VolumeItem
from vnpy.chart.item import ChartItem
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
from .trend_item import TrendLineItem
from ..engine import APP_NAME, EVENT_CHART_HISTORY, ChartWizardEngine

class CustomChartWidget(ChartWidget):
    """
    Custom ChartWidget that holds a reference to main_engine.
    """
    def __init__(self, main_engine: MainEngine) -> None:
        super().__init__()
        self._manager.main_engine = main_engine
        self.secondary_items: dict[str, tuple[ChartItem, pg.ViewBox]] = {}

    def add_secondary_item(
        self,
        item_class: type[ChartItem],
        item_name: str,
        plot_name: str
    ) -> None:
        plot: pg.PlotItem = self.get_plot(plot_name)
        if not plot:
            return

        # Create and link view
        view = pg.ViewBox()
        
        # Add view to plot scene
        plot.scene().addItem(view)

        # Link view to left axis
        plot.showAxis('left')
        plot.getAxis('left').linkToView(view)

        # Link x-axis
        view.setXLink(plot)

        # Create item
        item = item_class(self._manager)
        self._items[item_name] = item      # So it gets updates
        view.addItem(item)
        self.secondary_items[item_name] = (item, view)
        self._item_plot_map2[item] = plot  # For y-range update



        # Handle resize
        def update_view_geometry() -> None:
            view.setGeometry(plot.getViewBox().sceneBoundingRect())

        plot.getViewBox().sigResized.connect(update_view_geometry)
        update_view_geometry()  # Initial call

    def _update_y_range(self) -> None:
        """
        Update the y-axis range of plots.
        """
        super()._update_y_range()  # Do the original stuff

        if not self._first_plot:
            return

        view: pg.ViewBox = self._first_plot.getViewBox()
        view_range: list = view.viewRange()

        min_ix: int = max(0, int(view_range[0][0]))
        max_ix: int = min(self._manager.get_count(), int(view_range[0][1]))

        for item, view in self.secondary_items.values():
            y_range: tuple = item.get_y_range(min_ix, max_ix)
            view.setRange(yRange=y_range, padding=0.05)

    # Small fixed right-side margin (in bars) so the latest-point value
    # labels have a little room without a large empty gap.
    RIGHT_MARGIN_BARS: int = 4

    def move_to_right(self) -> None:
        """Snap to the right but leave a small fixed margin for the labels."""
        self._right_ix = self._manager.get_count() + self.RIGHT_MARGIN_BARS
        self._update_x_range()

    def _update_plot_limits(self) -> None:
        """Allow the pan/zoom limit to include the small right-side margin."""
        xmax: float = self._manager.get_count() + self.RIGHT_MARGIN_BARS
        for item, plot in self._item_plot_map.items():
            min_value, max_value = item.get_y_range()
            plot.setLimits(xMin=-1, xMax=xmax, yMin=min_value, yMax=max_value)


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

        # Track which symbols have finished loading history and seeding their
        # BarGenerator. Must be per-symbol: a shared flag lets ticks for a
        # newly-opened chart be processed before its history seeds the window
        # bar, so the first tick creates the forming window with open=current
        # price and the later history seed can no longer fix the open.
        self.history_inited: set[str] = set()
        self.init_ui()
        self.register_event()

    def init_ui(self) -> None:
        """初始化界面"""
        self.setWindowTitle("株価チャート")

        self.tab: QtWidgets.QTabWidget = QtWidgets.QTabWidget()

        self.tab.setTabsClosable(True)
        self.tab.tabCloseRequested.connect(self.close_tab)

        self.symbol_line: QtWidgets.QComboBox = QtWidgets.QComboBox()
        self.symbol_line.addItems(["nk-2608.JPX", "nk-2609.JPX"])

        self.interval_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()
        self.interval_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self.interval_combo.setMinimumContentsLength(5)
        self.interval_combo.setMinimumWidth(80)
        self.interval_combo.view().setMinimumWidth(80)
        for interval in [
            Interval.MINUTE,
            Interval.MINUTE3,
            Interval.MINUTE5,
            Interval.MINUTE6,
            Interval.MINUTE10,
            Interval.MINUTE15,
            Interval.MINUTE20,
            Interval.MINUTE30,
            Interval.HOUR,
            Interval.HOUR2,
            Interval.HOUR4,
            Interval.HOUR8,
            Interval.HOUR12,
            Interval.DAILY,
        ]:
            self.interval_combo.addItem(interval.value, interval)
        self.interval_combo.setCurrentIndex(
            self.interval_combo.findData(Interval.MINUTE15)
        )

        self.days_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.days_spin.setMinimum(3)
        self.days_spin.setMaximum(365)
        self.days_spin.setValue(45)
        self.days_spin.setSuffix("日")

        self.button: QtWidgets.QPushButton = QtWidgets.QPushButton("新規チャート")
        self.button.clicked.connect(self.new_chart)

        # Toggle the delta 0.02 (d002) put/call IV series on the IV subplot.
        self.d002_check: QtWidgets.QCheckBox = QtWidgets.QCheckBox("Δ0.02")
        self.d002_check.setChecked(False)
        self.d002_check.toggled.connect(self._on_d002_toggled)

        # Toggle the strike-roll (prev|now) labels on the IV subplot.
        self.strike_roll_check: QtWidgets.QCheckBox = QtWidgets.QCheckBox("行使価格変更")
        self.strike_roll_check.setChecked(True)
        self.strike_roll_check.toggled.connect(self._on_strike_roll_toggled)

        # Auto pivot trend lines (support/resistance) on the candle chart.
        self.trend_check: QtWidgets.QCheckBox = QtWidgets.QCheckBox("トレンドライン")
        self.trend_check.setChecked(True)
        self.trend_check.toggled.connect(self._on_trend_toggled)

        # Linear-regression channel on the candle chart.
        self.channel_check: QtWidgets.QCheckBox = QtWidgets.QCheckBox("チャネル")
        self.channel_check.setChecked(False)
        self.channel_check.toggled.connect(self._on_channel_toggled)

        # Show/hide the cursor cross-hair lines + labels (candle/iv_item/volume).
        self.cursor_check: QtWidgets.QCheckBox = QtWidgets.QCheckBox("カーソル")
        self.cursor_check.setChecked(False)
        self.cursor_check.toggled.connect(self._on_cursor_toggled)

        # Show/hide the last-price horizontal line + right-edge price tag.
        self.last_price_check: QtWidgets.QCheckBox = QtWidgets.QCheckBox("現在値")
        self.last_price_check.setChecked(True)
        self.last_price_check.toggled.connect(self._on_last_price_toggled)

        hbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox.addWidget(QtWidgets.QLabel("期間"))
        hbox.addWidget(self.days_spin)
        hbox.addWidget(QtWidgets.QLabel("銘柄コード"))
        hbox.addWidget(self.symbol_line)
        hbox.addWidget(QtWidgets.QLabel("時間足"))
        hbox.addWidget(self.interval_combo)
        hbox.addWidget(self.button)
        hbox.addWidget(self.d002_check)
        hbox.addWidget(self.strike_roll_check)
        hbox.addWidget(self.trend_check)
        hbox.addWidget(self.channel_check)
        hbox.addWidget(self.cursor_check)
        hbox.addWidget(self.last_price_check)
        hbox.addStretch()

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addLayout(hbox)
        vbox.addWidget(self.tab)

        self.setLayout(vbox)

    def create_chart(self) -> ChartWidget:
        """创建图表对象"""
        chart: ChartWidget = CustomChartWidget(self.main_engine)
        chart.add_plot("candle", hide_x_axis=True)
        chart.add_plot("otm_strike_iv", maximum_height=400, hide_x_axis=True)
        chart.add_plot("volume", maximum_height=100)

        chart.add_item(CandleItem, "candle", "candle")
        # Trend-line overlay shares the candle plot (added after candle so it
        # draws on top). Its y-range delegates to the candle item.
        chart.add_item(TrendLineItem, "trend", "candle")
        chart.add_item(IvItem, "otm_strike_iv", "otm_strike_iv")
        chart.add_item(VolumeItem, "volume", "volume")

        # set IvItem prev iv type
        chart._items["otm_strike_iv"].prev_iv_type = OptionPrevIvType.SAME_STRIKE
        # apply the current Δ0.02 toggle state to the new chart's IvItem
        chart._items["otm_strike_iv"].show_delta002 = self.d002_check.isChecked()
        # apply the current strike-roll label toggle state
        chart._items["otm_strike_iv"].show_strike_roll = self.strike_roll_check.isChecked()
        # wire the trend overlay: y-range delegation + current toggle states
        trend_item = chart._items["trend"]
        trend_item.candle_item = chart._items["candle"]
        trend_item.show_trend = self.trend_check.isChecked()
        trend_item.show_channel = self.channel_check.isChecked()
        # apply the current last-price line toggle state to the candle item
        chart._items["candle"].set_show_last_price(self.last_price_check.isChecked())

        chart.add_cursor()
        # Apply the current cursor show/hide state to the new chart.
        if chart._cursor is not None:
            chart._cursor.set_enabled(self.cursor_check.isChecked())
        return chart

    def _on_d002_toggled(self, checked: bool) -> None:
        """Show/hide the Δ0.02 IV series on every open chart's IV subplot."""
        for chart in self.charts.values():
            item = chart._items.get("otm_strike_iv")
            if isinstance(item, IvItem):
                item.set_show_delta002(checked)
            # Recompute the IV subplot y-range for the new visibility.
            chart._update_y_range()

    def _on_strike_roll_toggled(self, checked: bool) -> None:
        """Show/hide the strike-roll (prev|now) labels on every open chart."""
        for chart in self.charts.values():
            item = chart._items.get("otm_strike_iv")
            if isinstance(item, IvItem):
                item.set_show_strike_roll(checked)

    def _on_trend_toggled(self, checked: bool) -> None:
        """Show/hide the pivot trend lines on every open chart's candle plot."""
        for chart in self.charts.values():
            item = chart._items.get("trend")
            if isinstance(item, TrendLineItem):
                item.set_show_trend(checked)

    def _on_channel_toggled(self, checked: bool) -> None:
        """Show/hide the regression channel on every open chart's candle plot."""
        for chart in self.charts.values():
            item = chart._items.get("trend")
            if isinstance(item, TrendLineItem):
                item.set_show_channel(checked)

    def _on_cursor_toggled(self, checked: bool) -> None:
        """Show/hide the cursor cross-hair lines + labels on every open chart."""
        for chart in self.charts.values():
            if chart._cursor is not None:
                chart._cursor.set_enabled(checked)

    def _on_last_price_toggled(self, checked: bool) -> None:
        """Show/hide the last-price line + price tag on every open chart."""
        for chart in self.charts.values():
            item = chart._items.get("candle")
            if isinstance(item, CandleItem):
                item.set_show_last_price(checked)

    def show(self) -> None:
        """最大化显示"""
        self.showMaximized()

    def close_tab(self, index: int) -> None:
        """关闭标签"""
        vt_symbol: str = self.tab.tabText(index)

        self.tab.removeTab(index)
        self.charts.pop(vt_symbol)
        self.bgs.pop(vt_symbol)
        # Drop init flag so a reopened chart re-seeds its window from history
        # before live ticks are applied.
        self.history_inited.discard(vt_symbol)

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

        interval: Interval = self.interval_combo.currentData()

        # Create new chart
        bg_kwargs: dict = {
            "on_bar": self.on_bar,
            "on_window_bar": self.on_10min_bar,
            "interval": interval,
        }
        if interval == Interval.DAILY:
            bg_kwargs["daily_end"] = time(15, 45)
        self.bgs[vt_symbol] = BarGenerator(**bg_kwargs)
        self.bgs[vt_symbol].main_engine = self.main_engine

        chart: ChartWidget = self.create_chart()
        self.charts[vt_symbol] = chart

        self.tab.addTab(chart, vt_symbol)

        # Query history data
        end: datetime = datetime.now(ZoneInfo(get_localzone_name()))
        start: datetime = end - timedelta(days=self.days_spin.value())

        self.chart_engine.query_history(
            vt_symbol,
            interval,
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

        if bg and tick.vt_symbol in self.history_inited:
            bg.update_tick(tick)

            chart: ChartWidget = self.charts[tick.vt_symbol]
            bar: BarData = None
            # DAILY has no window value (not in the minute/hour maps) but must
            # still be aggregated into the current daily bar; otherwise the raw
            # 1-minute bar is pushed and a new bar is appended every minute.
            if bg.window > 0 or bg.interval == Interval.DAILY:
                # Update 1 minute bar into the current window / daily bar
                bar = copy(bg.bar)
                bg.update_bar(bar)
                # The daily path clears window_bar when a bar completes at
                # daily_end; nothing new to render for that tick.
                if bg.window_bar is None:
                    return
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
        self.history_inited.add(bar.vt_symbol)

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
