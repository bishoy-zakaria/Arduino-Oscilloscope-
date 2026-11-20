"""
Application Entry Point for ADC Oscilloscope.
"""

import argparse
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from adc_oscilloscope.gui_layer.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description="Arduino Uno ADC DAQ & 3-Plot Digital Oscilloscope")
    parser.add_argument("--port", type=str, default="", help="Serial port (e.g. COM3 or SIMULATOR)")
    parser.add_argument("--baud", type=int, default=1_000_000, help="Baud rate (default: 1,000,000)")
    parser.add_argument("--buffer-size", type=int, default=1_000_000, help="Capacity of sample buffer (default: 1,000,000)")
    parser.add_argument("--sim", action="store_true", help="Start directly in Simulator mode")
    args = parser.parse_args()

    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("ADC Oscilloscope")

    window = MainWindow(buffer_capacity=args.buffer_size)
    window.show()

    if args.sim:
        window._connect_serial("SIMULATOR", args.baud)
    elif args.port:
        window._connect_serial(args.port, args.baud)
    else:
        # Automatically connect to detected hardware port (e.g. COM14) or SIMULATOR
        window.auto_connect_default()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
