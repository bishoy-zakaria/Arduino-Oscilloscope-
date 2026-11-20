"""
GUI Layer: Control and Telemetry Panel.
Provides connection controls, oscilloscope timebases, zoom actions,
cursor readouts, live bus measurements, and Arduino hardware telemetry.
"""

from typing import List, Optional
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QPushButton,
    QComboBox,
    QLabel,
    QCheckBox,
    QDoubleSpinBox,
    QScrollArea,
    QFrame,
)


class ControlPanel(QWidget):
    """Side panel hosting all user controls and live telemetry displays."""

    # Signals
    connect_requested = pyqtSignal(str, int)
    disconnect_requested = pyqtSignal()
    ports_refresh_requested = pyqtSignal()
    pause_toggled = pyqtSignal(bool)  # True = Paused, False = Running
    timebase_selected = pyqtSignal(float)  # Time window in seconds (-1 for all)
    zoom_in_requested = pyqtSignal()
    zoom_out_requested = pyqtSignal()
    auto_fit_requested = pyqtSignal()
    cursors_toggled = pyqtSignal(bool)
    thresholds_changed = pyqtSignal(float, float)  # v_mid, hyst
    auto_threshold_requested = pyqtSignal()
    mode_changed = pyqtSignal(str)  # 'HYBRID' or 'RAW'
    export_csv_requested = pyqtSignal()
    sim_pwm_changed = pyqtSignal(float, float)  # freq, duty

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumWidth(320)
        self.setMaximumWidth(360)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        main_layout.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        self.layout = QVBoxLayout(container)
        self.layout.setSpacing(8)
        self.layout.setContentsMargins(4, 4, 4, 4)

        self._build_connection_group()
        self._build_signal_metrics_group()
        self._build_oscilloscope_controls()
        self._build_math_settings_group()
        self._build_arduino_telemetry_group()
        self._build_cursor_readout_group()
        self._build_simulator_controls_group()
        self._build_export_group()

        self.layout.addStretch()

    def _build_connection_group(self) -> None:
        group = QGroupBox("Physical Layer: Serial Connection")
        g_layout = QVBoxLayout(group)

        # Port row
        row_port = QHBoxLayout()
        self.combo_ports = QComboBox()
        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFixedWidth(30)
        self.btn_refresh.setToolTip("Refresh COM Ports")
        self.btn_refresh.clicked.connect(self.ports_refresh_requested.emit)

        row_port.addWidget(QLabel("Port:"))
        row_port.addWidget(self.combo_ports, 1)
        row_port.addWidget(self.btn_refresh)
        g_layout.addLayout(row_port)

        # Baud row
        row_baud = QHBoxLayout()
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["1000000", "500000", "115200"])
        row_baud.addWidget(QLabel("Baud:"))
        row_baud.addWidget(self.combo_baud, 1)
        g_layout.addLayout(row_baud)

        # Connect / Disconnect buttons
        row_btn = QHBoxLayout()
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setStyleSheet("background-color: #238636; color: white; font-weight: bold; padding: 5px;")
        self.btn_connect.clicked.connect(self._on_connect_clicked)

        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.setStyleSheet("background-color: #da3633; color: white; font-weight: bold; padding: 5px;")
        self.btn_disconnect.clicked.connect(self.disconnect_requested.emit)

        row_btn.addWidget(self.btn_connect)
        row_btn.addWidget(self.btn_disconnect)
        g_layout.addLayout(row_btn)

        # Connection status badge
        self.lbl_conn_status = QLabel("● Disconnected")
        self.lbl_conn_status.setStyleSheet("color: #8b949e; font-weight: bold;")
        g_layout.addWidget(self.lbl_conn_status)

        self.layout.addWidget(group)

    def _build_oscilloscope_controls(self) -> None:
        group = QGroupBox("Oscilloscope Controls")
        g_layout = QVBoxLayout(group)

        # RUN / PAUSE toggle button
        self.btn_run_pause = QPushButton("RUNNING  [Freeze / Pause]")
        self.btn_run_pause.setCheckable(True)
        self.btn_run_pause.setStyleSheet(
            "background-color: #1f6feb; color: white; font-weight: bold; font-size: 11pt; padding: 8px;"
        )
        self.btn_run_pause.toggled.connect(self._on_run_pause_toggled)
        g_layout.addWidget(self.btn_run_pause)

        # Timebase buttons
        g_layout.addWidget(QLabel("Horizontal Timebase Window:"))
        tb_layout = QGridLayout()
        tb_presets = [
            ("5 ms", 0.005),
            ("20 ms", 0.020),
            ("100 ms", 0.100),
            ("500 ms", 0.500),
            ("1.0 s", 1.000),
            ("ALL", -1.0),
        ]
        for idx, (label, val) in enumerate(tb_presets):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, v=val: self.timebase_selected.emit(v))
            tb_layout.addWidget(btn, idx // 3, idx % 3)
        g_layout.addLayout(tb_layout)

        # Zoom & Fit
        row_zoom = QHBoxLayout()
        self.btn_zoom_in = QPushButton("Zoom In (+)")
        self.btn_zoom_in.clicked.connect(self.zoom_in_requested.emit)
        self.btn_zoom_out = QPushButton("Zoom Out (-)")
        self.btn_zoom_out.clicked.connect(self.zoom_out_requested.emit)
        self.btn_autofit = QPushButton("Auto Fit")
        self.btn_autofit.clicked.connect(self.auto_fit_requested.emit)

        row_zoom.addWidget(self.btn_zoom_in)
        row_zoom.addWidget(self.btn_zoom_out)
        row_zoom.addWidget(self.btn_autofit)
        g_layout.addLayout(row_zoom)

        self.layout.addWidget(group)

    def _build_cursor_readout_group(self) -> None:
        group = QGroupBox("Measurement Cursors")
        g_layout = QVBoxLayout(group)

        self.chk_cursors = QCheckBox("Enable Oscilloscope Cursors")
        self.chk_cursors.toggled.connect(self.cursors_toggled.emit)
        g_layout.addWidget(self.chk_cursors)

        # Cursor readouts
        grid = QGridLayout()
        grid.addWidget(QLabel("T_A:"), 0, 0)
        self.lbl_cur_ta = QLabel("--")
        grid.addWidget(self.lbl_cur_ta, 0, 1)

        grid.addWidget(QLabel("T_B:"), 1, 0)
        self.lbl_cur_tb = QLabel("--")
        grid.addWidget(self.lbl_cur_tb, 1, 1)

        grid.addWidget(QLabel("ΔT:"), 2, 0)
        self.lbl_cur_dt = QLabel("--")
        self.lbl_cur_dt.setStyleSheet("color: #ffea00; font-weight: bold;")
        grid.addWidget(self.lbl_cur_dt, 2, 1)

        grid.addWidget(QLabel("1 / ΔT:"), 3, 0)
        self.lbl_cur_f = QLabel("--")
        self.lbl_cur_f.setStyleSheet("color: #ffab00; font-weight: bold;")
        grid.addWidget(self.lbl_cur_f, 3, 1)

        grid.addWidget(QLabel("V1:"), 4, 0)
        self.lbl_cur_v1 = QLabel("--")
        grid.addWidget(self.lbl_cur_v1, 4, 1)

        grid.addWidget(QLabel("V2:"), 5, 0)
        self.lbl_cur_v2 = QLabel("--")
        grid.addWidget(self.lbl_cur_v2, 5, 1)

        grid.addWidget(QLabel("ΔV:"), 6, 0)
        self.lbl_cur_dv = QLabel("--")
        self.lbl_cur_dv.setStyleSheet("color: #ff9100; font-weight: bold;")
        grid.addWidget(self.lbl_cur_dv, 6, 1)

        g_layout.addLayout(grid)
        self.layout.addWidget(group)

    def _build_signal_metrics_group(self) -> None:
        group = QGroupBox("Signal Measurements (DDAH Demodulated)")
        g_layout = QGridLayout(group)

        g_layout.addWidget(QLabel("Demod Freq:"), 0, 0)
        self.lbl_live_f = QLabel("-- Hz")
        self.lbl_live_f.setStyleSheet("color: #ffab00; font-weight: 800; font-size: 13pt;")
        g_layout.addWidget(self.lbl_live_f, 0, 1)

        g_layout.addWidget(QLabel("Demod Duty:"), 1, 0)
        self.lbl_live_duty = QLabel("-- %")
        self.lbl_live_duty.setStyleSheet("color: #e040fb; font-weight: 800; font-size: 13pt;")
        g_layout.addWidget(self.lbl_live_duty, 1, 1)

        g_layout.addWidget(QLabel("Raw Bus (Aliased):"), 2, 0)
        self.lbl_raw_bus = QLabel("-- Hz, -- %")
        self.lbl_raw_bus.setStyleSheet("color: #8b949e; font-size: 8.5pt;")
        g_layout.addWidget(self.lbl_raw_bus, 2, 1)

        g_layout.addWidget(QLabel("V_now:"), 3, 0)
        self.lbl_v_now = QLabel("0.00 V")
        self.lbl_v_now.setStyleSheet("color: #00e5ff; font-weight: bold;")
        g_layout.addWidget(self.lbl_v_now, 3, 1)

        g_layout.addWidget(QLabel("V_pp:"), 4, 0)
        self.lbl_v_pp = QLabel("0.00 V")
        g_layout.addWidget(self.lbl_v_pp, 4, 1)

        g_layout.addWidget(QLabel("V_max / Min:"), 5, 0)
        self.lbl_v_minmax = QLabel("0.00 / 0.00 V")
        g_layout.addWidget(self.lbl_v_minmax, 5, 1)

        g_layout.addWidget(QLabel("Cycles Processed:"), 6, 0)
        self.lbl_cycle_count = QLabel("0")
        g_layout.addWidget(self.lbl_cycle_count, 6, 1)

        self.layout.addWidget(group)

    def _build_math_settings_group(self) -> None:
        group = QGroupBox("Mathematical Demodulation Settings")
        g_layout = QGridLayout(group)

        # Mode Selection: DDAH Hybrid vs Raw Live
        g_layout.addWidget(QLabel("Mode:"), 0, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("DDAH Hybrid (Stabilized)", "HYBRID")
        self.combo_mode.addItem("Raw Live (Unfiltered)", "RAW")
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        g_layout.addWidget(self.combo_mode, 0, 1)

        g_layout.addWidget(QLabel("Threshold V_mid:"), 1, 0)
        self.spin_vmid = QDoubleSpinBox()
        self.spin_vmid.setRange(0.1, 4.9)
        self.spin_vmid.setSingleStep(0.05)
        self.spin_vmid.setValue(2.5)
        self.spin_vmid.setSuffix(" V")
        self.spin_vmid.valueChanged.connect(self._on_threshold_changed)
        g_layout.addWidget(self.spin_vmid, 1, 1)

        g_layout.addWidget(QLabel("Hysteresis ΔV:"), 2, 0)
        self.spin_hyst = QDoubleSpinBox()
        self.spin_hyst.setRange(0.05, 2.0)
        self.spin_hyst.setSingleStep(0.05)
        self.spin_hyst.setValue(0.5)
        self.spin_hyst.setSuffix(" V")
        self.spin_hyst.valueChanged.connect(self._on_threshold_changed)
        g_layout.addWidget(self.spin_hyst, 2, 1)

        self.btn_auto_thresh = QPushButton("Auto-Detect Threshold")
        self.btn_auto_thresh.clicked.connect(self.auto_threshold_requested.emit)
        g_layout.addWidget(self.btn_auto_thresh, 3, 0, 1, 2)

        self.layout.addWidget(group)

    def _build_arduino_telemetry_group(self) -> None:
        group = QGroupBox("Arduino Uno Telemetry (Live Registers)")
        g_layout = QGridLayout(group)

        g_layout.addWidget(QLabel("F_CPU:"), 0, 0)
        self.lbl_fcpu = QLabel("16.0 MHz")
        g_layout.addWidget(self.lbl_fcpu, 0, 1)

        g_layout.addWidget(QLabel("Timer 1 (PWM):"), 1, 0)
        self.lbl_pwm_reg = QLabel("ICR1: -, OCR1A: -")
        g_layout.addWidget(self.lbl_pwm_reg, 1, 1)

        g_layout.addWidget(QLabel("HW Calc PWM:"), 2, 0)
        self.lbl_hw_pwm = QLabel("- Hz, - %")
        self.lbl_hw_pwm.setStyleSheet("color: #7ee787;")
        g_layout.addWidget(self.lbl_hw_pwm, 2, 1)

        g_layout.addWidget(QLabel("Timer 2 (ADC):"), 3, 0)
        self.lbl_adc_rate = QLabel("OCR2A: 79 (25 kSPS)")
        g_layout.addWidget(self.lbl_adc_rate, 3, 1)

        g_layout.addWidget(QLabel("Throughput:"), 4, 0)
        self.lbl_throughput = QLabel("0 pkts/s (0 KB/s)")
        g_layout.addWidget(self.lbl_throughput, 4, 1)

        self.layout.addWidget(group)

    def _build_simulator_controls_group(self) -> None:
        self.sim_group = QGroupBox("Simulator PWM Injector")
        g_layout = QGridLayout(self.sim_group)

        g_layout.addWidget(QLabel("Sim Freq:"), 0, 0)
        self.spin_sim_f = QDoubleSpinBox()
        self.spin_sim_f.setRange(10.0, 5000.0)
        self.spin_sim_f.setValue(400.0)
        self.spin_sim_f.setSuffix(" Hz")
        self.spin_sim_f.valueChanged.connect(self._on_sim_pwm_changed)
        g_layout.addWidget(self.spin_sim_f, 0, 1)

        g_layout.addWidget(QLabel("Sim Duty:"), 1, 0)
        self.spin_sim_d = QDoubleSpinBox()
        self.spin_sim_d.setRange(0.0, 100.0)
        self.spin_sim_d.setValue(50.0)
        self.spin_sim_d.setSuffix(" %")
        self.spin_sim_d.valueChanged.connect(self._on_sim_pwm_changed)
        g_layout.addWidget(self.spin_sim_d, 1, 1)

        self.layout.addWidget(self.sim_group)
        self.sim_group.setVisible(False)

    def _build_export_group(self) -> None:
        group = QGroupBox("Data Export")
        g_layout = QVBoxLayout(group)

        self.btn_export = QPushButton("Export Buffer to CSV")
        self.btn_export.setStyleSheet("background-color: #30363d; padding: 6px;")
        self.btn_export.clicked.connect(self.export_csv_requested.emit)
        g_layout.addWidget(self.btn_export)

        self.layout.addWidget(group)

    # Handlers & Public Setters
    def _on_connect_clicked(self) -> None:
        port = self.combo_ports.currentText().strip()
        baud = int(self.combo_baud.currentText())
        self.connect_requested.emit(port, baud)

    def _on_run_pause_toggled(self, paused: bool) -> None:
        if paused:
            self.btn_run_pause.setText("PAUSED  [Click to Resume]")
            self.btn_run_pause.setStyleSheet(
                "background-color: #d29922; color: #0d1117; font-weight: bold; font-size: 11pt; padding: 8px;"
            )
        else:
            self.btn_run_pause.setText("RUNNING  [Freeze / Pause]")
            self.btn_run_pause.setStyleSheet(
                "background-color: #1f6feb; color: white; font-weight: bold; font-size: 11pt; padding: 8px;"
            )
        self.pause_toggled.emit(paused)

    def _on_threshold_changed(self) -> None:
        v_mid = self.spin_vmid.value()
        hyst = self.spin_hyst.value()
        self.thresholds_changed.emit(v_mid, hyst)

    def _on_mode_changed(self) -> None:
        mode_val = self.combo_mode.currentData()
        self.mode_changed.emit(mode_val)

    def _on_sim_pwm_changed(self) -> None:
        f = self.spin_sim_f.value()
        d = self.spin_sim_d.value()
        self.sim_pwm_changed.emit(f, d)

    def set_ports(self, ports: List[str]) -> None:
        curr = self.combo_ports.currentText()
        self.combo_ports.clear()
        self.combo_ports.addItems(ports)
        if curr in ports:
            self.combo_ports.setCurrentText(curr)

    def set_connected_state(self, connected: bool, message: str, is_sim: bool = False) -> None:
        self.btn_connect.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        self.combo_ports.setEnabled(not connected)
        self.combo_baud.setEnabled(not connected)
        self.sim_group.setVisible(connected and is_sim)

        if connected:
            self.lbl_conn_status.setText(f"● {message}")
            self.lbl_conn_status.setStyleSheet("color: #3fb950; font-weight: bold;")
        else:
            self.lbl_conn_status.setText("● Disconnected")
            self.lbl_conn_status.setStyleSheet("color: #8b949e; font-weight: bold;")

    def update_cursor_readouts(self, data: dict) -> None:
        self.lbl_cur_ta.setText(f"{data['ta']:.5f} s")
        self.lbl_cur_tb.setText(f"{data['tb']:.5f} s")

        dt = data['dt']
        if dt < 1e-3:
            self.lbl_cur_dt.setText(f"{dt * 1e6:.1f} µs")
        elif dt < 1.0:
            self.lbl_cur_dt.setText(f"{dt * 1e3:.3f} ms")
        else:
            self.lbl_cur_dt.setText(f"{dt:.4f} s")

        f = data['cursor_freq']
        if f >= 1000.0:
            self.lbl_cur_f.setText(f"{f/1000.0:.3f} kHz")
        else:
            self.lbl_cur_f.setText(f"{f:.2f} Hz")

        self.lbl_cur_v1.setText(f"{data['v1']:.3f} V")
        self.lbl_cur_v2.setText(f"{data['v2']:.3f} V")
        self.lbl_cur_dv.setText(f"{data['dv']:.3f} V")

    def update_signal_metrics(
        self,
        v_now: float,
        v_min: float,
        v_max: float,
        f_live: float,
        duty_live: float,
        count: int,
        raw_f: float = 0.0,
        raw_d: float = 0.0,
    ) -> None:
        self.lbl_v_now.setText(f"{v_now:.2f} V")
        self.lbl_v_pp.setText(f"{(v_max - v_min):.2f} V")
        self.lbl_v_minmax.setText(f"{v_max:.2f} / {v_min:.2f} V")

        if f_live > 0:
            if f_live >= 1000.0:
                self.lbl_live_f.setText(f"{f_live/1000.0:.3f} kHz")
            else:
                self.lbl_live_f.setText(f"{f_live:.2f} Hz")
        else:
            self.lbl_live_f.setText("-- Hz")

        if duty_live > 0 or f_live > 0:
            self.lbl_live_duty.setText(f"{duty_live:.2f} %")
        else:
            self.lbl_live_duty.setText("-- %")

        if raw_f > 0:
            if raw_f >= 1000.0:
                self.lbl_raw_bus.setText(f"{raw_f/1000.0:.2f} kHz, {raw_d:.1f}%")
            else:
                self.lbl_raw_bus.setText(f"{raw_f:.1f} Hz, {raw_d:.1f}%")
        else:
            self.lbl_raw_bus.setText("-- Hz, -- %")

        self.lbl_cycle_count.setText(f"{count:,}")

    def update_arduino_telemetry(
        self,
        f_cpu: int,
        pwm_icr1: int,
        pwm_ocr1a: int,
        pwm_psc: int,
        adc_ocr2a: int,
        adc_psc: int,
        pkts_sec: float,
        bytes_sec: float,
    ) -> None:
        self.lbl_fcpu.setText(f"{f_cpu / 1e6:.1f} MHz")
        self.lbl_pwm_reg.setText(f"ICR1:{pwm_icr1}, OCR1A:{pwm_ocr1a}, /N:{pwm_psc}")

        if f_cpu > 0 and pwm_psc > 0 and (pwm_icr1 + 1) > 0:
            hw_f = float(f_cpu) / (float(pwm_psc) * float(pwm_icr1 + 1))
            hw_d = (float(pwm_ocr1a) / float(pwm_icr1 + 1)) * 100.0
            self.lbl_hw_pwm.setText(f"{hw_f:.1f} Hz, {hw_d:.1f}%")

        if f_cpu > 0 and adc_psc > 0:
            sample_rate = float(f_cpu) / (float(adc_psc) * float(adc_ocr2a + 1))
            self.lbl_adc_rate.setText(f"OCR2A: {adc_ocr2a} ({sample_rate/1000.0:.1f} kSPS)")

        self.lbl_throughput.setText(f"{pkts_sec:.0f} pkts/s ({(bytes_sec/1024.0):.1f} KB/s)")
