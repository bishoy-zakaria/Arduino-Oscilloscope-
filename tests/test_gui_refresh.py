"""
Test GUI Data Refresh and Live Plot Rendering with COM14.
Verifies Qt event loop processing, live curve data population,
plot refreshing, and measurement updates.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from adc_oscilloscope.gui_layer.main_window import MainWindow


def test_gui_refresh_live(port: str = "COM14", duration_s: float = 3.5):
    print("==================================================")
    print(f"      TESTING GUI LIVE DATA REFRESH ON {port}")
    print("==================================================")

    # Initialize Qt Application
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    window = MainWindow(buffer_capacity=500_000)
    window.show()

    print(f"[Step 1] Connecting MainWindow to {port} @ 1,000,000 baud...")
    window._connect_serial(port, 1_000_000)

    # Allow bootloader reset + streaming data + GUI event loop execution
    start_time = time.perf_counter()
    refresh_frames_observed = 0
    curve_lengths = []

    print("[Step 2] Running Qt event loop and monitoring live plot refresh...")
    while (time.perf_counter() - start_time) < duration_s:
        app.processEvents()
        time.sleep(0.02)

        # Check voltage curve data in PyQtGraph
        x_data, y_data = window.scope_view.curve_volt.getData()
        if x_data is not None and len(x_data) > 0:
            refresh_frames_observed += 1
            curve_lengths.append(len(x_data))

    # Read data from the live plots
    v_x, v_y = window.scope_view.curve_volt.getData()
    f_x, f_y = window.scope_view.curve_freq.getData()
    d_x, d_y = window.scope_view.curve_duty.getData()

    print("\n---------------- GUI Live Plot Verification ----------------")
    print(f"  GUI Refresh Ticks Observed : {refresh_frames_observed}")
    print(f"  Voltage Curve Points       : {len(v_x) if v_x is not None else 0}")
    print(f"  Frequency Curve Points     : {len(f_x) if f_x is not None else 0}")
    print(f"  Duty Cycle Curve Points    : {len(d_x) if d_x is not None else 0}")
    print(f"  Live V_now Label           : {window.ctrl_panel.lbl_v_now.text()}")
    print(f"  Live V_pp Label            : {window.ctrl_panel.lbl_v_pp.text()}")
    print(f"  Live Freq Label            : {window.ctrl_panel.lbl_live_f.text()}")
    print(f"  Live Duty Label            : {window.ctrl_panel.lbl_live_duty.text()}")
    print(f"  Throughput Label           : {window.ctrl_panel.lbl_throughput.text()}")
    print(f"  Cycles Counted Label       : {window.ctrl_panel.lbl_cycle_count.text()}")

    # Test Pause function
    print("\n[Step 3] Testing Oscilloscope Pause (Freeze)...")
    window._toggle_pause(True)
    app.processEvents()
    time.sleep(0.1)
    paused_state = window.is_paused
    print(f"  Is Paused                  : {paused_state}")

    # Test Resume function
    print("\n[Step 4] Testing Oscilloscope Resume...")
    window._toggle_pause(False)
    app.processEvents()
    time.sleep(0.1)
    resumed_state = not window.is_paused
    print(f"  Is Resumed                 : {resumed_state}")

    # Test Zoom function
    print("\n[Step 5] Testing Horizontal Zoom & Timebase...")
    window._set_timebase(0.020)  # 20 ms
    app.processEvents()
    window.scope_view.zoom_in(0.5)
    app.processEvents()
    view_range = window.scope_view.p_volt.getViewBox().viewRange()[0]
    print(f"  Zoomed X-Range             : {view_range[1] - view_range[0]:.4f} s")

    # Disconnect & Close
    window.close()
    app.processEvents()

    # Assertions
    assert v_x is not None and len(v_x) > 100, f"Voltage curve has insufficient points: {len(v_x) if v_x is not None else 0}"
    assert refresh_frames_observed > 10, f"Insufficient GUI refresh ticks observed: {refresh_frames_observed}"
    assert paused_state is True, "Pause state failed"
    assert resumed_state is True, "Resume state failed"

    print("\n==================================================")
    print("   >>> GUI REFRESH AND DATA TEST COMPLETED! <<<   ")
    print("==================================================")
    return True


if __name__ == "__main__":
    target_port = sys.argv[1] if len(sys.argv) > 1 else "COM14"
    ok = test_gui_refresh_live(port=target_port)
    sys.exit(0 if ok else 1)
