"""
Physical Layer: Serial Receiver Worker.
Handles real UART streaming from Arduino Uno or fallback internal simulator,
feeding parsed frames directly into the StorageBuffer.
"""

import threading
import time
from typing import Callable, List, Optional
import serial
import serial.tools.list_ports

from .packet_parser import StreamParser, AdcFrame
from .storage_buffer import StorageBuffer
from .simulator import ArduinoSimulator


class SerialReceiver:
    """
    Manages serial reception thread, frame parsing, and buffer population.
    Supports physical COM ports and internal hardware simulator.
    """

    def __init__(
        self,
        storage_buffer: StorageBuffer,
        on_connection_change: Optional[Callable[[bool, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.storage_buffer = storage_buffer
        self.on_connection_change = on_connection_change
        self.on_error = on_error

        self.parser = StreamParser()
        self._serial: Optional[serial.Serial] = None
        self._simulator: Optional[ArduinoSimulator] = None

        self._running = False
        self._thread: Optional[threading.Thread] = None

        self.current_port: str = ""
        self.current_baudrate: int = 1_000_000
        self.is_simulator: bool = False
        self._write_lock = threading.Lock()

        # Live performance counters
        self.packets_per_sec: float = 0.0
        self.bytes_per_sec: float = 0.0
        self._packet_counter: int = 0
        self._byte_counter: int = 0
        self._last_rate_calc_time = time.perf_counter()

    @staticmethod
    def list_ports() -> List[str]:
        """Returns list of available serial port names, including simulator option."""
        ports = [p.device for p in serial.tools.list_ports.comports()]
        return ["SIMULATOR"] + ports

    def is_connected(self) -> bool:
        return self._running

    def connect(self, port: str, baudrate: int = 1_000_000) -> bool:
        """Connect to a serial port or launch simulator."""
        if self._running:
            self.disconnect()

        self.current_port = port.strip()
        self.current_baudrate = int(baudrate)
        self.parser.reset()
        self._packet_counter = 0
        self._byte_counter = 0
        self._last_rate_calc_time = time.perf_counter()

        if self.current_port.upper() == "SIMULATOR":
            self.is_simulator = True
            self._simulator = ArduinoSimulator(
                pwm_freq=400.0,
                pwm_duty=50.0,
                on_packet_bytes=self._on_simulator_bytes
            )
            self._running = True
            self._simulator.start()
            if self.on_connection_change:
                self.on_connection_change(True, "Connected to internal Simulator (25 kSPS)")
            return True

        # Physical serial port
        self.is_simulator = False
        try:
            self._serial = serial.Serial(
                port=self.current_port,
                baudrate=self.current_baudrate,
                timeout=0.05,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
            )
            # Flush existing buffers
            self._serial.reset_input_buffer()
        except Exception as e:
            err_msg = f"Failed to open port {self.current_port}: {e}"
            if self.on_error:
                self.on_error(err_msg)
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._serial_read_loop,
            daemon=True,
            name="SerialReceiverLoop"
        )
        self._thread.start()

        if self.on_connection_change:
            self.on_connection_change(True, f"Connected to {self.current_port} @ {self.current_baudrate} baud")
        return True

    def disconnect(self) -> None:
        """Disconnect and stop background worker threads."""
        self._running = False

        if self._simulator:
            self._simulator.stop()
            self._simulator = None

        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

        self.packets_per_sec = 0.0
        self.bytes_per_sec = 0.0

        if self.on_connection_change:
            self.on_connection_change(False, "Disconnected")

    def _serial_read_loop(self) -> None:
        """Continuous background reading loop for serial port."""
        while self._running and self._serial and self._serial.is_open:
            try:
                waiting = self._serial.in_waiting
                to_read = max(waiting, 1) if waiting > 0 else 1
                chunk = self._serial.read(to_read)
                if chunk:
                    self._process_chunk(chunk)
                else:
                    time.sleep(0.001)
            except Exception as e:
                if self._running:
                    err = f"Serial read error: {e}"
                    if self.on_error:
                        self.on_error(err)
                    break
        if self._running:
            self.disconnect()

    def _on_simulator_bytes(self, chunk: bytes) -> None:
        """Direct stream input from internal simulator."""
        if self._running:
            self._process_chunk(chunk)

    def _process_chunk(self, chunk: bytes) -> None:
        """Process incoming raw byte stream, extract frames, and buffer data."""
        self._byte_counter += len(chunk)
        now = time.perf_counter()
        dt = now - self._last_rate_calc_time
        if dt >= 0.5:
            self.packets_per_sec = self._packet_counter / dt
            self.bytes_per_sec = self._byte_counter / dt
            self._packet_counter = 0
            self._byte_counter = 0
            self._last_rate_calc_time = now

        for frame in self.parser.parse_stream(chunk):
            self._packet_counter += 1
            # Push into high-capacity ring buffer
            self.storage_buffer.append(
                timestamps=frame.timestamps_s,
                voltages=frame.voltages,
                raw_adc=frame.raw_samples,
                timestamp_us=frame.timestamp_us,
                f_cpu=frame.f_cpu_hz,
                pwm_icr1=frame.pwm_icr1,
                pwm_ocr1a=frame.pwm_ocr1a,
                pwm_prescaler=frame.pwm_prescaler,
                adc_ocr2a=frame.adc_ocr2a,
                adc_prescaler=frame.adc_prescaler,
            )

    def update_simulator_pwm(self, freq: float, duty: float) -> None:
        """Update simulator PWM if running."""
        if self._simulator and self._simulator.is_running():
            self._simulator.set_pwm(freq, duty)

    def set_pwm(self, freq: float, duty: float) -> None:
        """Dynamically update PWM on physical Arduino or internal simulator."""
        if self.is_simulator:
            self.update_simulator_pwm(freq, duty)
        elif self._serial and self._serial.is_open:
            with self._write_lock:
                try:
                    cmd = f"F:{freq:.1f},D:{duty:.1f}\n".encode("ascii")
                    self._serial.write(cmd)
                    self._serial.flush()
                except Exception as e:
                    if self.on_error:
                        self.on_error(f"Failed to send PWM command: {e}")
