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

        # Manual range trend lines: user-picked [start, end] x-ranges, each
        # drawn with its own support + resistance pair (dashed, to distinguish
        # from the auto lines). Right-click near one to delete it.
        self._manual_ranges: list[tuple[int, int]] = []
        # Per-range drawn geometry, kept for right-click hit-testing:
        # list of (range, [(x0, y0, x1, y1), ...]).
        self._manual_geoms: list[tuple[tuple[int, int], list[tuple[float, float, float, float]]]] = []

        self._manual_res_pen: QtGui.QPen = pg.mkPen(color=ORANGE_COLOR, width=2)
        self._manual_res_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        self._manual_sup_pen: QtGui.QPen = pg.mkPen(color=SPRING_GREEN_COLOR, width=2)
        self._manual_sup_pen.setStyle(QtCore.Qt.PenStyle.DashLine)

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
        # Bar indices change on reload, so stale manual ranges are dropped.
        self._manual_ranges = []
        self._manual_geoms = []
        for lbl in self._degree_labels:
            lbl.hide()
        super().clear_all()

    # ------------------------------------------------------- manual range lines
    def add_manual_range(self, x0: int, x1: int) -> None:
        """Add a manual support+resistance pair fitted to the [x0, x1] range."""
        start, end = (int(x0), int(x1)) if x0 <= x1 else (int(x1), int(x0))
        if end - start < 2:
            return
        self._manual_ranges.append((start, end))
        self._recompute()

    def clear_manual(self) -> None:
        """Remove all manual range trend lines."""
        if not self._manual_ranges:
            return
        self._manual_ranges = []
        self._recompute()

    def set_manual_ranges(self, ranges: list[tuple[int, int]]) -> None:
        """Replace all manual ranges (used when restoring saved lines)."""
        self._manual_ranges = [(int(a), int(b)) for (a, b) in ranges]
        self._recompute()

    def remove_manual_at(self, xv: float, yv: float, vb: pg.ViewBox, tol_px: float = 8.0) -> bool:
        """Delete the manual range whose support/resistance line is closest to
        (xv, yv) in pixel space, if within tol_px. Returns True if one removed."""
        if not self._manual_geoms:
            return False
        (x0v, x1v), (y0v, y1v) = vb.viewRange()
        vw, vh = vb.width(), vb.height()
        if not (vw > 0 and vh > 0 and x1v > x0v and y1v > y0v):
            return False
        sx: float = vw / (x1v - x0v)        # pixels per bar
        sy: float = vh / (y1v - y0v)        # pixels per price unit
        best_range: tuple[int, int] | None = None
        best_dist: float = tol_px
        for rng, geoms in self._manual_geoms:
            for gx0, gy0, gx1, gy1 in geoms:
                d = self._point_seg_dist_px(xv, yv, gx0, gy0, gx1, gy1, sx, sy)
                if d <= best_dist:
                    best_dist = d
                    best_range = rng
        if best_range is None:
            return False
        try:
            self._manual_ranges.remove(best_range)
        except ValueError:
            return False
        self._recompute()
        return True

    @staticmethod
    def _point_seg_dist_px(px: float, py: float, x0: float, y0: float,
                           x1: float, y1: float, sx: float, sy: float) -> float:
        """Distance from point to segment, measured in on-screen pixels."""
        ax, ay = px * sx, py * sy
        bx0, by0 = x0 * sx, y0 * sy
        bx1, by1 = x1 * sx, y1 * sy
        dx, dy = bx1 - bx0, by1 - by0
        if dx == 0 and dy == 0:
            return ((ax - bx0) ** 2 + (ay - by0) ** 2) ** 0.5
        t = ((ax - bx0) * dx + (ay - by0) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        cx, cy = bx0 + t * dx, by0 + t * dy
        return ((ax - cx) ** 2 + (ay - cy) ** 2) ** 0.5

    def _fit_range_lines(self, start: int, end: int):
        """Fit a support + resistance line across the [start, end] bar range.

        Anchors are the two most extreme swing pivots inside the range (highest
        highs for resistance, lowest lows for support); if fewer than two
        pivots exist, the two extreme bars in the range are used. Each line is
        projected across the whole range. Returns (res, sup) as
        (x0, y0, x1, y1) tuples (either may be None)."""
        bars: list[BarData] = self._manager.get_all_bars()
        n: int = len(bars)
        if n == 0:
            return None
        start = max(0, min(int(start), n - 1))
        end = max(0, min(int(end), n - 1))
        if start > end:
            start, end = end, start
        if end - start < 2:
            return None

        highs, lows = self._find_pivots(bars)
        r_piv = [(i, p) for (i, p) in highs if start <= i <= end]
        s_piv = [(i, p) for (i, p) in lows if start <= i <= end]
        res = self._range_line(r_piv, bars, start, end, use_high=True)
        sup = self._range_line(s_piv, bars, start, end, use_high=False)
        return res, sup

    @staticmethod
    def _range_line(pivots, bars, start, end, use_high: bool):
        """Pick two anchors and project a line across [start, end]."""
        if len(pivots) >= 2:
            ordered = sorted(pivots, key=lambda t: t[1], reverse=use_high)
            (xa, ya), (xb, yb) = ordered[0], ordered[1]
        else:
            idxs = list(range(start, end + 1))
            key = (lambda i: bars[i].high_price) if use_high else (lambda i: bars[i].low_price)
            idxs.sort(key=key, reverse=use_high)
            if len(idxs) < 2:
                return None
            i0, i1 = idxs[0], idxs[1]
            xa, ya = i0, (bars[i0].high_price if use_high else bars[i0].low_price)
            xb, yb = i1, (bars[i1].high_price if use_high else bars[i1].low_price)
        if xa == xb:
            return None
        slope = (yb - ya) / (xb - xa)
        y_start = ya + slope * (start - xa)
        y_end = ya + slope * (end - xa)
        return (float(start), float(y_start), float(end), float(y_end))

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

        # --- Manual range trend lines (always shown, not gated by toggles) ----
        self._manual_geoms = []
        for rng in self._manual_ranges:
            fit = self._fit_range_lines(rng[0], rng[1])
            if fit is None:
                continue
            res, sup = fit
            geoms: list[tuple[float, float, float, float]] = []
            if res is not None:
                self._segments.append((res[0], res[1], res[2], res[3], self._manual_res_pen, True))
                geoms.append(res)
                ys += [res[1], res[3]]
            if sup is not None:
                self._segments.append((sup[0], sup[1], sup[2], sup[3], self._manual_sup_pen, True))
                geoms.append(sup)
                ys += [sup[1], sup[3]]
            if geoms:
                self._manual_geoms.append((rng, geoms))

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
            # Price at the line's own endpoint (x1) — i.e. the last bar of its
            # range: the whole chart's latest bar for auto トレンドライン, or the
            # user-selected end bar for 範囲トレンド. This is the crossing level
            # to use as a candidate entry.
            lbl.setColor(pen.color())
            lbl.setText(f"{angle:+.0f}°  {y1:,.0f}")
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
