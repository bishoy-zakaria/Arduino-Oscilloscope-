"""
GUI Layer: Oscilloscope Main Application Window.
Coordinates Physical Layer, Mathematical Layer, and PyQtGraph Oscilloscope View.
"""

import csv
import os
import time
from typing import Optional
import numpy as np
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QMessageBox,
    QFileDialog,
    QStatusBar,
)

from ..physical_layer.storage_buffer import StorageBuffer
from ..physical_layer.serial_receiver import SerialReceiver
from ..math_layer.edge_detector import EdgeDetector
from .oscilloscope_view import OscilloscopeView
from .control_panel import ControlPanel


class MainWindow(QMainWindow):
    """Main window integrating the 3 layers into a high-speed live digital oscilloscope."""

    def __init__(self, buffer_capacity: int = 1_000_000, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Arduino Uno ADC DAQ & Oscilloscope [25 kSPS Live Bus]")
        self.resize(1350, 850)

        # 1. Physical Layer Storage
        self.storage_buffer = StorageBuffer(capacity=buffer_capacity)
        self.receiver = SerialReceiver(
            storage_buffer=self.storage_buffer,
            on_connection_change=self._on_connection_changed,
            on_error=self._on_receiver_error,
        )

        # 2. Mathematical Layer
        self.edge_detector = EdgeDetector(v_mid=2.5, hysteresis=0.5, max_history=100_000)

        # 3. GUI Layer
        self.scope_view = OscilloscopeView()
        self.ctrl_panel = ControlPanel()

        self._init_layout()
        self._connect_signals()

        # State tracking
        self.is_paused: bool = False
        self.active_timebase_s: float = 0.050  # 50 ms default window
        self._last_processed_sample_total: int = 0

        # High-speed GUI refresh timer (30-40 FPS)
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(28)  # ~35 FPS
        self._render_timer.timeout.connect(self._on_render_tick)
        self._render_timer.start()

        # Populate available ports on startup
        self._refresh_ports()

        # Apply dark oscilloscope stylesheet
        self._apply_theme()

    def _init_layout(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Left: Oscilloscope 3 live plots
        layout.addWidget(self.scope_view, 1)

        # Right: Control and telemetry panel
        layout.addWidget(self.ctrl_panel, 0)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Select COM Port or Simulator to start acquisition.")

    def _connect_signals(self) -> None:
        # Control panel signals
        self.ctrl_panel.connect_requested.connect(self._connect_serial)
        self.ctrl_panel.disconnect_requested.connect(self._disconnect_serial)
        self.ctrl_panel.ports_refresh_requested.connect(self._refresh_ports)
        self.ctrl_panel.pause_toggled.connect(self._toggle_pause)
        self.ctrl_panel.timebase_selected.connect(self._set_timebase)
        self.ctrl_panel.zoom_in_requested.connect(self._zoom_in)
        self.ctrl_panel.zoom_out_requested.connect(self._zoom_out)
        self.ctrl_panel.auto_fit_requested.connect(self._auto_fit)
        self.ctrl_panel.cursors_toggled.connect(self.scope_view.set_cursors_visible)
        self.ctrl_panel.thresholds_changed.connect(self._on_thresholds_changed)
        self.ctrl_panel.auto_threshold_requested.connect(self._auto_detect_threshold)
        self.ctrl_panel.mode_changed.connect(self._on_demod_mode_changed)
        self.ctrl_panel.export_csv_requested.connect(self._export_to_csv)
        self.ctrl_panel.sim_pwm_changed.connect(self.receiver.set_pwm)

        # Oscilloscope cursor readouts
        self.scope_view.cursor_moved.connect(self.ctrl_panel.update_cursor_readouts)

    def _apply_theme(self) -> None:
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d1117;
            }
            QWidget {
                background-color: #0d1117;
                color: #c9d1d9;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QGroupBox {
                border: 1px solid #30363d;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 10px;
                font-weight: bold;
                color: #58a6ff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
            }
            QPushButton {
                background-color: #21262d;
                border: 1px solid #363b42;
                border-radius: 4px;
                color: #c9d1d9;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #8b949e;
            }
            QPushButton:pressed {
                background-color: #161b22;
            }
            QComboBox, QDoubleSpinBox {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 4px;
                padding: 3px 6px;
                color: #c9d1d9;
            }
            QStatusBar {
                background-color: #161b22;
                color: #8b949e;
                border-top: 1px solid #21262d;
            }
        """)

    def _refresh_ports(self) -> None:
        ports = SerialReceiver.list_ports()
        self.ctrl_panel.set_ports(ports)

    def _connect_serial(self, port: str, baudrate: int) -> None:
        self.status_bar.showMessage(f"Connecting to {port} @ {baudrate} baud...")
        # Reset state cleanly on new connection
        self.storage_buffer.clear()
        self.edge_detector.reset()
        self._last_processed_sample_total = 0

        success = self.receiver.connect(port, baudrate)
        if not success:
            self.status_bar.showMessage(f"Failed to connect to {port}")

    def _disconnect_serial(self) -> None:
        self.receiver.disconnect()

    def _on_connection_changed(self, connected: bool, message: str) -> None:
        self.ctrl_panel.set_connected_state(
            connected, message, is_sim=self.receiver.is_simulator
        )
        self.status_bar.showMessage(message)

    def _on_receiver_error(self, err_msg: str) -> None:
        self.status_bar.showMessage(f"Error: {err_msg}")

    def _toggle_pause(self, paused: bool) -> None:
        self.is_paused = paused
        if paused:
            self.status_bar.showMessage("Oscilloscope PAUSED (Display frozen - zoom/pan enabled)")
        else:
            self.status_bar.showMessage("Oscilloscope RUNNING (Live streaming)")

    def _set_timebase(self, window_s: float) -> None:
        self.active_timebase_s = window_s

    def _zoom_in(self) -> None:
        self.scope_view.zoom_in(0.5)

    def _zoom_out(self) -> None:
        self.scope_view.zoom_out(2.0)

    def _auto_fit(self) -> None:
        self.scope_view.auto_fit_y()
        self.active_timebase_s = 0.050

    def _on_thresholds_changed(self, v_mid: float, hyst: float) -> None:
        self.edge_detector.set_thresholds(v_mid, hyst)
        self.scope_view.set_threshold_display(v_mid)

    def _on_demod_mode_changed(self, mode: str) -> None:
        self.edge_detector.set_mode(mode)
        self.status_bar.showMessage(f"Demodulation Mode switched to: {self.edge_detector.mode}")

    def _auto_detect_threshold(self) -> None:
        ts, volt = self.storage_buffer.get_latest(2000)
        if len(volt) > 50:
            v_mid, hyst = self.edge_detector.auto_adjust_thresholds(volt)
            self.ctrl_panel.spin_vmid.setValue(v_mid)
            self.ctrl_panel.spin_hyst.setValue(hyst)
            self.scope_view.set_threshold_display(v_mid)
            self.status_bar.showMessage(f"Auto threshold set: V_mid={v_mid:.2f}V, Hyst=±{hyst:.2f}V")

    def _on_render_tick(self) -> None:
        """Periodic tick: feeds new samples into Math Layer and refreshes GUI plots."""
        # 1. Feed newly arrived samples to Mathematical Layer
        if self._last_processed_sample_total > self.storage_buffer.total_samples:
            self._last_processed_sample_total = 0

        new_ts, new_volt, new_total = self.storage_buffer.get_new_since(
            self._last_processed_sample_total
        )
        if len(new_volt) > 0:
            self.edge_detector.process_samples(new_ts, new_volt)
            self._last_processed_sample_total = new_total

        # 2. Always update live metrics & HUD banner on every tick with fresh values
        f_live = self.edge_detector.latest_frequency
        duty_live = self.edge_detector.latest_duty
        raw_f = self.edge_detector.latest_raw_frequency
        raw_d = self.edge_detector.latest_raw_duty
        cycles_count = self.edge_detector.total_cycles
        v_min = self.edge_detector.v_base
        v_max = self.edge_detector.v_top
        v_now = float(new_volt[-1]) if len(new_volt) > 0 else 0.0

        self.scope_view.update_hud(
            f_live=f_live,
            duty_live=duty_live,
            v_min=v_min,
            v_max=v_max,
            mode=self.edge_detector.mode,
        )

        self.ctrl_panel.update_signal_metrics(
            v_now=v_now,
            v_min=v_min,
            v_max=v_max,
            f_live=f_live,
            duty_live=duty_live,
            count=cycles_count,
            raw_f=raw_f,
            raw_d=raw_d,
        )

        # 3. Update telemetry display continuously
        self.ctrl_panel.update_arduino_telemetry(
            f_cpu=self.storage_buffer.latest_f_cpu,
            pwm_icr1=self.storage_buffer.latest_pwm_icr1,
            pwm_ocr1a=self.storage_buffer.latest_pwm_ocr1a,
            pwm_psc=self.storage_buffer.latest_pwm_prescaler,
            adc_ocr2a=self.storage_buffer.latest_adc_ocr2a,
            adc_psc=self.storage_buffer.latest_adc_prescaler,
            pkts_sec=self.receiver.packets_per_sec,
            bytes_sec=self.receiver.bytes_per_sec,
        )

        # 4. If paused, do not scroll plots (user is actively zooming/inspecting)
        if self.is_paused:
            return

        # 5. Fetch data for live plotting
        total_stored = self.storage_buffer.current_size
        if total_stored == 0:
            return

        if self.active_timebase_s > 0:
            # Approximate samples needed: window_s * 25 kSPS
            samples_needed = int(self.active_timebase_s * 25000.0)
            t_plot, v_plot = self.storage_buffer.get_latest(samples_needed)
        else:
            # Full buffer view
            t_plot, v_plot = self.storage_buffer.get_all()

        if len(t_plot) == 0:
            return

        # Update Voltage trace (with auto-decimation if > 4000 points to keep 60 FPS)
        if len(t_plot) > 4000:
            step = int(np.ceil(len(t_plot) / 4000.0))
            self.scope_view.update_voltage_plot(t_plot[::step], v_plot[::step])
        else:
            self.scope_view.update_voltage_plot(t_plot, v_plot)

        # Set horizontal range to match latest time window (guaranteeing t_start < t_end)
        t_end = t_plot[-1]
        if self.active_timebase_s > 0:
            t_start = max(t_plot[0], t_end - self.active_timebase_s)
        else:
            t_start = t_plot[0]
        if t_end <= t_start:
            t_end = t_start + max(1e-3, self.active_timebase_s)
        self.scope_view.set_time_range(t_start, t_end)

        # Update Cycle plots (Frequency and Duty Cycle) with latest visible cycles
        t_cyc, f_cyc, d_cyc = self.edge_detector.get_latest(500)
        self.scope_view.update_cycle_plots(t_cyc, f_cyc, d_cyc)

    def auto_connect_default(self) -> None:
        """Auto-connect to available physical Arduino port (e.g. COM14), or fallback to SIMULATOR."""
        ports = SerialReceiver.list_ports()
        hw_ports = [p for p in ports if p != "SIMULATOR"]
        target = hw_ports[0] if hw_ports else "SIMULATOR"
        self.ctrl_panel.combo_ports.setCurrentText(target)
        self._connect_serial(target, 1_000_000)

    def _export_to_csv(self) -> None:
        """Export current instantaneous buffer and cycle measurements to CSV."""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Oscilloscope Capture CSV", "oscilloscope_capture.csv", "CSV Files (*.csv)"
        )
        if not filepath:
            return

        t_all, v_all = self.storage_buffer.get_all()
        t_cyc, f_cyc, d_cyc = self.edge_detector.get_all()

        try:
            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["# Oscilloscope Capture Data"])
                writer.writerow(["# Total Samples", len(t_all)])
                writer.writerow(["# Total Cycles", len(t_cyc)])
                writer.writerow([])
                writer.writerow(["Time_s", "Voltage_V"])
                for ti, vi in zip(t_all, v_all):
                    writer.writerow([f"{ti:.6f}", f"{vi:.4f}"])

            self.status_bar.showMessage(f"Exported {len(t_all)} samples to {os.path.basename(filepath)}")
            QMessageBox.information(self, "Export Complete", f"Data saved successfully to:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to save CSV:\n{e}")

    def closeEvent(self, event) -> None:
        """Ensure clean shutdown of serial and simulation threads."""
        self._render_timer.stop()
        self.receiver.disconnect()
        event.accept()
