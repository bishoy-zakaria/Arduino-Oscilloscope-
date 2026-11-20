"""
GUI Layer: High-Performance Oscilloscope View with 3 Live Plots & Cursors.
Uses PyQtGraph for hardware-accelerated 60 FPS oscilloscope visualization.
Features a top Heads-Up Display (HUD) banner for prominent Frequency & Duty readouts.
"""

from typing import Optional, Tuple
import numpy as np
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor, QFont, QPen
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
import pyqtgraph as pg


class OscilloscopeView(QWidget):
    """
    Oscilloscope View containing 3 synchronized plots:
    1. Instantaneous Voltage (V vs Time)
    2. Instantaneous Frequency (Hz vs Time)
    3. Instantaneous Duty Cycle (% vs Time)
    Includes interactive dual time & voltage cursors, threshold indicators,
    and a prominent top HUD banner for instantaneous Frequency and Duty readings.
    """

    cursor_moved = pyqtSignal(dict)  # Emits cursor readouts

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Global PyQtGraph config
        pg.setConfigOption("background", "#0d1117")
        pg.setConfigOption("foreground", "#c9d1d9")
        pg.setConfigOption("antialias", True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)

        # Color palette
        self.c_volt = "#00e5ff"  # Phosphor Cyan
        self.c_freq = "#ffab00"  # Amber Gold
        self.c_duty = "#e040fb"  # Bright Magenta
        self.c_grid = "#21262d"

        # 1. Top HUD Live Readout Banner
        self._build_top_hud()

        # 2. Graphics layout widget hosting the 3 plots
        self.glw = pg.GraphicsLayoutWidget()
        self._layout.addWidget(self.glw)

        self._init_plots()
        self._init_cursors()
        self._init_threshold_line()

        self.cursors_visible = False
        self.set_cursors_visible(False)

    def _build_top_hud(self) -> None:
        """Create sleek, prominent digital HUD readout cards at the top of the scope."""
        hud_frame = QFrame()
        hud_frame.setStyleSheet("""
            QFrame {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        hud_layout = QHBoxLayout(hud_frame)
        hud_layout.setContentsMargins(12, 6, 12, 6)
        hud_layout.setSpacing(16)

        # 1. Frequency Card
        box_f = QVBoxLayout()
        box_f.setSpacing(1)
        lbl_f_title = QLabel("CARRIER FREQUENCY")
        lbl_f_title.setStyleSheet("font-size: 8pt; font-weight: bold; color: #8b949e; letter-spacing: 0.05em;")
        self.hud_freq_val = QLabel("-- Hz")
        self.hud_freq_val.setStyleSheet("font-size: 17pt; font-weight: 800; color: #ffab00; font-family: monospace;")
        box_f.addWidget(lbl_f_title)
        box_f.addWidget(self.hud_freq_val)
        hud_layout.addLayout(box_f)

        self._add_hud_divider(hud_layout)

        # 2. Duty Cycle Card
        box_d = QVBoxLayout()
        box_d.setSpacing(1)
        lbl_d_title = QLabel("DUTY CYCLE")
        lbl_d_title.setStyleSheet("font-size: 8pt; font-weight: bold; color: #8b949e; letter-spacing: 0.05em;")
        self.hud_duty_val = QLabel("-- %")
        self.hud_duty_val.setStyleSheet("font-size: 17pt; font-weight: 800; color: #e040fb; font-family: monospace;")
        box_d.addWidget(lbl_d_title)
        box_d.addWidget(self.hud_duty_val)
        hud_layout.addLayout(box_d)

        self._add_hud_divider(hud_layout)

        # 3. Peak-to-Peak Voltage Card
        box_v = QVBoxLayout()
        box_v.setSpacing(1)
        lbl_v_title = QLabel("AMPLITUDE V_PP")
        lbl_v_title.setStyleSheet("font-size: 8pt; font-weight: bold; color: #8b949e; letter-spacing: 0.05em;")
        self.hud_vpp_val = QLabel("0.00 V")
        self.hud_vpp_val.setStyleSheet("font-size: 17pt; font-weight: 800; color: #00e5ff; font-family: monospace;")
        box_v.addWidget(lbl_v_title)
        box_v.addWidget(self.hud_vpp_val)
        hud_layout.addLayout(box_v)

        self._add_hud_divider(hud_layout)

        # 4. Status / Demodulation Mode Card
        box_st = QVBoxLayout()
        box_st.setSpacing(1)
        lbl_st_title = QLabel("DEMODULATION STATUS")
        lbl_st_title.setStyleSheet("font-size: 8pt; font-weight: bold; color: #8b949e; letter-spacing: 0.05em;")
        self.hud_status_val = QLabel("DDAH HYBRID (WAITING)")
        self.hud_status_val.setStyleSheet("font-size: 12pt; font-weight: bold; color: #3fb950;")
        box_st.addWidget(lbl_st_title)
        box_st.addWidget(self.hud_status_val)
        hud_layout.addLayout(box_st)

        hud_layout.addStretch()
        self._layout.addWidget(hud_frame)

    def _add_hud_divider(self, layout: QHBoxLayout) -> None:
        div = QFrame()
        div.setFrameShape(QFrame.Shape.VLine)
        div.setFrameShadow(QFrame.Shadow.Sunken)
        div.setStyleSheet("color: #30363d;")
        layout.addWidget(div)

    def update_hud(
        self, f_live: float, duty_live: float, v_min: float, v_max: float, mode: str
    ) -> None:
        """Update values in the top HUD banner."""
        if f_live > 0:
            if f_live >= 1000.0:
                self.hud_freq_val.setText(f"{f_live/1000.0:.3f} kHz")
            else:
                self.hud_freq_val.setText(f"{f_live:.2f} Hz")
        else:
            self.hud_freq_val.setText("-- Hz")

        if duty_live > 0 or f_live > 0:
            self.hud_duty_val.setText(f"{duty_live:.2f} %")
        else:
            self.hud_duty_val.setText("-- %")

        v_pp = max(0.0, v_max - v_min)
        self.hud_vpp_val.setText(f"{v_pp:.2f} V")

        status_color = "#3fb950" if f_live > 0 else "#8b949e"
        status_text = f"{mode} (LOCKED)" if f_live > 0 else f"{mode} (IDLE)"
        self.hud_status_val.setText(status_text)
        self.hud_status_val.setStyleSheet(f"font-size: 12pt; font-weight: bold; color: {status_color};")

    def _init_plots(self) -> None:
        """Create and configure the three stacked plots."""
        # 1. Voltage Plot
        self.p_volt = self.glw.addPlot(row=0, col=0)
        self.p_volt.showGrid(x=True, y=True, alpha=0.3)
        self.p_volt.setLabel("left", "Voltage", units="V", color=self.c_volt)
        self.p_volt.setLabel("bottom", "Time", units="s")
        self.p_volt.setYRange(-0.2, 5.3, padding=0.02)
        self.p_volt.setTitle(
            '<span style="color:#00e5ff; font-weight:bold; font-size:11pt;">Channel 1: Instantaneous Voltage V(t) [25 kSPS Raw Bus]</span>'
        )

        # Voltage curve
        self.curve_volt = self.p_volt.plot(
            pen=pg.mkPen(color=self.c_volt, width=1.8),
            name="Voltage",
        )

        # 2. Frequency Plot
        self.p_freq = self.glw.addPlot(row=1, col=0)
        self.p_freq.showGrid(x=True, y=True, alpha=0.3)
        self.p_freq.setLabel("left", "Freq", units="Hz", color=self.c_freq)
        self.p_freq.setLabel("bottom", "Time", units="s")
        self.p_freq.setTitle(
            '<span style="color:#ffab00; font-weight:bold; font-size:11pt;">Channel 2: Demodulated Frequency (Hz)</span>'
        )
        self.p_freq.enableAutoRange(axis=pg.ViewBox.YAxis)
        self.curve_freq = self.p_freq.plot(
            pen=pg.mkPen(color=self.c_freq, width=2.0),
            name="Frequency",
        )

        # 3. Duty Cycle Plot
        self.p_duty = self.glw.addPlot(row=2, col=0)
        self.p_duty.showGrid(x=True, y=True, alpha=0.3)
        self.p_duty.setLabel("left", "Duty", units="%", color=self.c_duty)
        self.p_duty.setLabel("bottom", "Time", units="s")
        self.p_duty.setYRange(0.0, 100.0, padding=0.05)
        self.p_duty.setTitle(
            '<span style="color:#e040fb; font-weight:bold; font-size:11pt;">Channel 3: Demodulated Duty Cycle (%)</span>'
        )
        self.curve_duty = self.p_duty.plot(
            pen=pg.mkPen(color=self.c_duty, width=2.0),
            name="Duty",
        )

        # Synchronize X axes so panning/zooming one pans all
        self.p_freq.setXLink(self.p_volt)
        self.p_duty.setXLink(self.p_volt)

    def _init_cursors(self) -> None:
        """Create vertical time cursors and horizontal voltage cursors."""
        pen_ca = pg.mkPen(color="#ffea00", width=1.5, style=Qt.PenStyle.DashLine)
        pen_cb = pg.mkPen(color="#00e676", width=1.5, style=Qt.PenStyle.DashLine)

        self.cursor_ta = pg.InfiniteLine(
            pos=0.01, angle=90, movable=True, pen=pen_ca, label="T_A: {value:.5f}s",
            labelOpts={"color": "#ffea00", "position": 0.95}
        )
        self.cursor_tb = pg.InfiniteLine(
            pos=0.03, angle=90, movable=True, pen=pen_cb, label="T_B: {value:.5f}s",
            labelOpts={"color": "#00e676", "position": 0.85}
        )

        self.p_volt.addItem(self.cursor_ta)
        self.p_volt.addItem(self.cursor_tb)

        self.cursor_ta.sigPositionChanged.connect(self._on_cursor_change)
        self.cursor_tb.sigPositionChanged.connect(self._on_cursor_change)

        pen_v1 = pg.mkPen(color="#ff9100", width=1.5, style=Qt.PenStyle.DashDotLine)
        pen_v2 = pg.mkPen(color="#ff3d00", width=1.5, style=Qt.PenStyle.DashDotLine)

        self.cursor_v1 = pg.InfiniteLine(
            pos=1.0, angle=0, movable=True, pen=pen_v1, label="V1: {value:.2f}V",
            labelOpts={"color": "#ff9100", "position": 0.05}
        )
        self.cursor_v2 = pg.InfiniteLine(
            pos=4.0, angle=0, movable=True, pen=pen_v2, label="V2: {value:.2f}V",
            labelOpts={"color": "#ff3d00", "position": 0.15}
        )

        self.p_volt.addItem(self.cursor_v1)
        self.p_volt.addItem(self.cursor_v2)

        self.cursor_v1.sigPositionChanged.connect(self._on_cursor_change)
        self.cursor_v2.sigPositionChanged.connect(self._on_cursor_change)

    def _init_threshold_line(self) -> None:
        """Create visual indicator for mathematical edge detection midpoint."""
        pen_th = pg.mkPen(color="#78909c", width=1, style=Qt.PenStyle.DotLine)
        self.line_vmid = pg.InfiniteLine(
            pos=2.5, angle=0, movable=False, pen=pen_th, label="V_th: 2.5V",
            labelOpts={"color": "#78909c", "position": 0.9}
        )
        self.p_volt.addItem(self.line_vmid)

    def set_threshold_display(self, v_mid: float) -> None:
        """Update visual threshold line."""
        self.line_vmid.setValue(v_mid)
        self.line_vmid.label.setText(f"V_th: {v_mid:.2f}V")

    def set_cursors_visible(self, visible: bool) -> None:
        """Toggle visibility of interactive measurement cursors."""
        self.cursors_visible = visible
        self.cursor_ta.setVisible(visible)
        self.cursor_tb.setVisible(visible)
        self.cursor_v1.setVisible(visible)
        self.cursor_v2.setVisible(visible)
        if visible:
            self._on_cursor_change()

    def _on_cursor_change(self) -> None:
        if not self.cursors_visible:
            return

        ta = self.cursor_ta.value()
        tb = self.cursor_tb.value()
        dt = abs(tb - ta)
        f_meas = (1.0 / dt) if dt > 0.0 else 0.0

        v1 = self.cursor_v1.value()
        v2 = self.cursor_v2.value()
        dv = abs(v2 - v1)

        readouts = {
            "ta": ta,
            "tb": tb,
            "dt": dt,
            "cursor_freq": f_meas,
            "v1": v1,
            "v2": v2,
            "dv": dv,
        }
        self.cursor_moved.emit(readouts)

    def update_voltage_plot(self, t: np.ndarray, v: np.ndarray) -> None:
        """Update waveform data in the Voltage plot."""
        if len(t) > 0 and len(v) > 0:
            self.curve_volt.setData(t, v)

    def update_cycle_plots(
        self, t_cyc: np.ndarray, f_cyc: np.ndarray, d_cyc: np.ndarray
    ) -> None:
        """Update frequency and duty cycle curves and dynamic ranges."""
        if len(t_cyc) > 0 and len(f_cyc) > 0:
            self.curve_freq.setData(t_cyc, f_cyc)
            self.curve_duty.setData(t_cyc, d_cyc)

            # Auto-scale Frequency Y axis around active frequency
            f_last = float(f_cyc[-1])
            if f_last > 0:
                f_margin = max(50.0, 0.25 * f_last)
                self.p_freq.setYRange(max(0.0, f_last - f_margin), f_last + f_margin, padding=0.05)
                # Update title with latest values
                if f_last >= 1000.0:
                    self.p_freq.setTitle(f'<span style="color:#ffab00; font-weight:bold; font-size:11pt;">Channel 2: Demodulated Frequency: {f_last/1000.0:.3f} kHz</span>')
                else:
                    self.p_freq.setTitle(f'<span style="color:#ffab00; font-weight:bold; font-size:11pt;">Channel 2: Demodulated Frequency: {f_last:.2f} Hz</span>')

            d_last = float(d_cyc[-1])
            if d_last >= 0:
                self.p_duty.setTitle(f'<span style="color:#e040fb; font-weight:bold; font-size:11pt;">Channel 3: Demodulated Duty Cycle: {d_last:.2f}%</span>')

    def set_time_range(self, t_min: float, t_max: float) -> None:
        """Set horizontal viewing window."""
        self.p_volt.setXRange(t_min, t_max, padding=0.0)

    def zoom_in(self, factor: float = 0.5) -> None:
        """Zoom in time horizontally."""
        view_box = self.p_volt.getViewBox()
        x_min, x_max = view_box.viewRange()[0]
        center = (x_min + x_max) / 2.0
        span = (x_max - x_min) * factor
        self.p_volt.setXRange(center - span / 2.0, center + span / 2.0, padding=0.0)

    def zoom_out(self, factor: float = 2.0) -> None:
        """Zoom out time horizontally."""
        view_box = self.p_volt.getViewBox()
        x_min, x_max = view_box.viewRange()[0]
        center = (x_min + x_max) / 2.0
        span = (x_max - x_min) * factor
        self.p_volt.setXRange(center - span / 2.0, center + span / 2.0, padding=0.0)

    def auto_fit_y(self) -> None:
        """Auto-scale Y axes to fit active signals."""
        self.p_volt.setYRange(-0.1, 5.2, padding=0.02)
        self.p_duty.setYRange(0.0, 100.0, padding=0.05)
        self.p_freq.enableAutoRange(axis=pg.ViewBox.YAxis)
