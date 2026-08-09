from typing import Optional

import numpy as np
import pyqtgraph as pg

from vnpy.chart.base import (
    PEN_WIDTH, ORANGE_COLOR, SPRING_GREEN_COLOR, YELLOW_COLOR, GREY_COLOR,
)
from vnpy.chart.item import ChartItem
from vnpy.chart.manager import BarManager
from vnpy.trader.ui import QtCore, QtGui
from vnpy.trader.object import BarData


class TrendLineItem(ChartItem):
    """
    Overlay item on the futures candle plot that automatically draws:

      * Pivot trend lines — connect the two most recent swing highs
        (resistance) and swing lows (support), projected to the last bar.
      * Regression channel — least-squares line over the last N bars, with
        ±kσ bands (channel top / bottom).

    Both are computed locally (no network / AI service) and recomputed on
    every bar update. Each is toggled independently from the toolbar.

    The item shares the candle plot, so its get_y_range delegates to the
    CandleItem to avoid overriding the plot's price range.
    """

    def __init__(self, manager: BarManager) -> None:
        super().__init__(manager)

        # Toggles (set from the toolbar checkboxes).
        self.show_trend: bool = False
        self.show_channel: bool = False

        # Delegate y-range to this item so the candle plot range is unchanged.
        self.candle_item: Optional[ChartItem] = None

        # Parameters.
        self.pivot_lookback: int = 3        # bars each side to define a pivot
        self.channel_window: int = 60       # bars used for the regression channel
        self.channel_sigma: float = 2.0     # band width in residual std devs

        # Pens (cosmetic → constant pixel width regardless of zoom).
        self._res_pen: QtGui.QPen = pg.mkPen(color=ORANGE_COLOR, width=2)
        self._sup_pen: QtGui.QPen = pg.mkPen(color=SPRING_GREEN_COLOR, width=2)

        self._chan_mid_pen: QtGui.QPen = pg.mkPen(color=YELLOW_COLOR, width=2)
        self._chan_mid_pen.setStyle(QtCore.Qt.PenStyle.DotLine)
        self._chan_band_pen: QtGui.QPen = pg.mkPen(color=GREY_COLOR, width=1.5)
        self._chan_band_pen.setStyle(QtCore.Qt.PenStyle.DashLine)

        # Computed line segments: (x0, y0, x1, y1, pen, label?) — label flags
        # whether to annotate that segment with its slope angle (skip the
        # parallel channel bands so only the mid-line is labelled).
        self._segments: list[tuple[float, float, float, float, QtGui.QPen, bool]] = []
        self._bound_lo: float = 0.0
        self._bound_hi: float = 0.0

        # Reusable pool of slope-angle labels (pg.TextItem).
        self._degree_labels: list[pg.TextItem] = []

    # ------------------------------------------------------------------ toggles
    def set_show_trend(self, show: bool) -> None:
        if self.show_trend == show:
            return
        self.show_trend = show
        self._recompute()

    def set_show_channel(self, show: bool) -> None:
        if self.show_channel == show:
            return
        self.show_channel = show
        self._recompute()

    # ------------------------------------------------------------------ updates
    def update_bar(self, bar: BarData) -> None:
        super().update_bar(bar)
        self._recompute()

    def update_history(self, history: list[BarData]) -> None:
        super().update_history(history)
        self._recompute()

    def clear_all(self) -> None:
        self._segments = []
        for lbl in self._degree_labels:
            lbl.hide()
        super().clear_all()

    # ------------------------------------------------------------------ compute
    def _find_pivots(self, bars: list[BarData]) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        """Return (swing_highs, swing_lows) as lists of (index, price)."""
        k: int = self.pivot_lookback
        highs: list[tuple[int, float]] = []
        lows: list[tuple[int, float]] = []
        n: int = len(bars)
        for i in range(k, n - k):
            hi: float = bars[i].high_price
            lo: float = bars[i].low_price
            window = bars[i - k:i + k + 1]
            # Strict local extreme (the pivot bar alone holds the extreme).
            if hi == max(b.high_price for b in window) and \
                    sum(1 for b in window if b.high_price == hi) == 1:
                highs.append((i, hi))
            if lo == min(b.low_price for b in window) and \
                    sum(1 for b in window if b.low_price == lo) == 1:
                lows.append((i, lo))
        return highs, lows

    def _recompute(self) -> None:
        """Rebuild the trend / channel segments from the current bars."""
        self.prepareGeometryChange()
        self._segments = []

        bars: list[BarData] = self._manager.get_all_bars()
        n: int = len(bars)
        if n < 5:
            self.update()
            return

        last_ix: int = n - 1
        ys: list[float] = []

        # --- Pivot trend lines ------------------------------------------------
        if self.show_trend:
            highs, lows = self._find_pivots(bars)

            # Resistance: connect the two most recent swing highs, projected to
            # the last bar along that slope.
            if len(highs) >= 2:
                (x0, y0), (x1, y1) = highs[-2], highs[-1]
                if x1 != x0:
                    slope = (y1 - y0) / (x1 - x0)
                    y_end = y1 + slope * (last_ix - x1)
                    self._segments.append((x0, y0, last_ix, y_end, self._res_pen, True))
                    ys += [y0, y_end]

            # Support: connect the two most recent swing lows.
            if len(lows) >= 2:
                (x0, y0), (x1, y1) = lows[-2], lows[-1]
                if x1 != x0:
                    slope = (y1 - y0) / (x1 - x0)
                    y_end = y1 + slope * (last_ix - x1)
                    self._segments.append((x0, y0, last_ix, y_end, self._sup_pen, True))
                    ys += [y0, y_end]

        # --- Regression channel ----------------------------------------------
        if self.show_channel:
            w: int = min(self.channel_window, n)
            start_ix: int = n - w
            closes = np.array([b.close_price for b in bars[start_ix:]], dtype=float)
            xr = np.arange(w, dtype=float)
            slope, intercept = np.polyfit(xr, closes, 1)
            mid = slope * xr + intercept
            resid = closes - mid
            sigma = float(np.std(resid)) or 0.0
            band = self.channel_sigma * sigma

            x_left: int = start_ix
            x_right: int = last_ix
            mid_left = float(mid[0])
            mid_right = float(mid[-1])
            self._segments.append((x_left, mid_left, x_right, mid_right, self._chan_mid_pen, True))
            self._segments.append((x_left, mid_left + band, x_right, mid_right + band, self._chan_band_pen, False))
            self._segments.append((x_left, mid_left - band, x_right, mid_right - band, self._chan_band_pen, False))
            ys += [mid_left + band, mid_right + band, mid_left - band, mid_right - band]

        if ys:
            self._bound_lo = min(ys)
            self._bound_hi = max(ys)
        self.update()

    # ------------------------------------------------------------------ drawing
    def paint(self, painter: QtGui.QPainter, opt, w) -> None:  # type: ignore[override]
        if not self._segments:
            for lbl in self._degree_labels:
                lbl.hide()
            return
        for x0, y0, x1, y1, pen, _label in self._segments:
            painter.setPen(pen)
            painter.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(x1, y1))
        self._update_degree_labels()

    def _update_degree_labels(self) -> None:
        """Annotate labelled segments with their on-screen slope angle.

        The angle is the *visual* slope in pixel space (price and bar axes
        have different scales), so it depends on the current zoom and is
        recomputed each paint. Up-slope → +[0,90]°, down-slope → -[0,90]°.
        """
        vb = self.getViewBox()
        if vb is None:
            for lbl in self._degree_labels:
                lbl.hide()
            return

        (x0v, x1v), (y0v, y1v) = vb.viewRange()
        vw: float = vb.width()
        vh: float = vb.height()
        if not (vw > 0 and vh > 0 and x1v > x0v and y1v > y0v):
            for lbl in self._degree_labels:
                lbl.hide()
            return
        px_x: float = vw / (x1v - x0v)      # pixels per bar
        px_y: float = vh / (y1v - y0v)      # pixels per price unit

        labelled = [s for s in self._segments if s[5]]

        while len(self._degree_labels) < len(labelled):
            lbl = pg.TextItem(anchor=(0.0, 0.5))
            lbl.setFont(QtGui.QFont("", 8))
            vb.addItem(lbl, ignoreBounds=True)
            self._degree_labels.append(lbl)

        for i, lbl in enumerate(self._degree_labels):
            if i >= len(labelled):
                lbl.hide()
                continue
            x0, y0, x1, y1, pen, _label = labelled[i]
            dx_px: float = (x1 - x0) * px_x
            dy_px: float = (y1 - y0) * px_y     # data y-up → positive = up-slope
            angle: float = float(np.degrees(np.arctan2(dy_px, dx_px)))
            lbl.setColor(pen.color())
            lbl.setText(f"{angle:+.0f}°")
            # Nudge the label a small gap to the right of the last bar so the
            # text does not overlap the endpoint / candle.
            lbl.setPos(x1 + 0.6, y1)
            lbl.show()

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """Unused — this item overrides paint() directly."""
        return QtGui.QPicture()

    def boundingRect(self) -> QtCore.QRectF:
        """Cover the full x-range and a y-range spanning price + drawn lines."""
        min_price, max_price = self._manager.get_price_range()
        lo = min(min_price, self._bound_lo) if self._segments else min_price
        hi = max(max_price, self._bound_hi) if self._segments else max_price
        return QtCore.QRectF(0, lo, max(1, self._manager.get_count()), hi - lo)

    def get_y_range(self, min_ix: int | None = None, max_ix: int | None = None) -> tuple[float, float]:
        """Delegate to the candle item so the plot's price range is unchanged."""
        if self.candle_item is not None:
            return self.candle_item.get_y_range(min_ix, max_ix)
        return self._manager.get_price_range(min_ix, max_ix)

    def get_info_text(self, ix: int) -> str:
        return ""
