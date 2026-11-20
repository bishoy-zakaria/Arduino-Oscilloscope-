"""
Physical Layer: Arduino Uno Hardware Simulator.
Simulates the exact 25 kSPS Timer2 ADC DAQ and Timer1 PWM generator.
Allows offline testing and validation when physical hardware is not plugged in.
"""

import threading
import time
from typing import Callable, Optional
import numpy as np

from .packet_parser import pack_adc_packet, SAMPLES_PER_PACKET


class ArduinoSimulator:
    """
    Simulates the Arduino Uno DAQ firmware:
    Generates realistic 0xAA 0x55 binary frames at 250 Hz (100 samples every 4 ms).
    Simulates Timer1 PWM output sampled by Timer2 at 25 kSPS (40 us interval).
    """

    def __init__(
        self,
        pwm_freq: float = 400.0,
        pwm_duty: float = 50.0,
        noise_amplitude: float = 0.02, # 20 mV ADC noise
        v_high: float = 4.85,
        v_low: float = 0.10,
        on_packet_bytes: Optional[Callable[[bytes], None]] = None
    ):
        self.pwm_freq = float(pwm_freq)
        self.pwm_duty = float(pwm_duty)
        self.noise_amplitude = float(noise_amplitude)
        self.v_high = float(v_high)
        self.v_low = float(v_low)
        self.on_packet_bytes = on_packet_bytes

        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Arduino hardware constants
        self.f_cpu_hz = 16_000_000
        self.adc_ocr2a = 79
        self.adc_prescaler = 8
        self.sample_period_s = 40.0e-6 # 40 us

        # Simulated timer registers
        self._calc_pwm_registers()

    def _calc_pwm_registers(self) -> None:
        """Calculates ICR1, OCR1A, and prescaler matching arduinoUNO_ADC.ino."""
        prescalers = [1, 8, 64, 256, 1024]
        self.pwm_prescaler = 8
        self.pwm_icr1 = 4999
        self.pwm_ocr1a = 2500

        for psc in prescalers:
            top_exact = (float(self.f_cpu_hz) / (float(psc) * self.pwm_freq)) - 1.0
            if 1.0 <= top_exact <= 65535.0:
                self.pwm_prescaler = psc
                self.pwm_icr1 = int(round(top_exact))
                break

        period_ticks = self.pwm_icr1 + 1
        ocr = (self.pwm_duty / 100.0) * period_ticks
        self.pwm_ocr1a = int(round(ocr))

    def set_pwm(self, freq: float, duty: float) -> None:
        """Dynamically update the simulated PWM frequency and duty cycle."""
        self.pwm_freq = max(1.0, float(freq))
        self.pwm_duty = max(0.0, min(100.0, float(duty)))
        self._calc_pwm_registers()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ArduinoSimulator")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def is_running(self) -> bool:
        return self._running

    def _run_loop(self) -> None:
        packet_period_s = SAMPLES_PER_PACKET * self.sample_period_s  # 4.0 ms (250 Hz)
        start_wall_time = time.perf_counter()
        packet_count = 0
        current_time_s = 0.0

        while self._running:
            target_time = start_wall_time + (packet_count + 1) * packet_period_s
            now = time.perf_counter()
            sleep_sec = target_time - now
            if sleep_sec > 0:
                time.sleep(sleep_sec)

            packet_count += 1
            # Generate 100 samples
            t_samples = current_time_s + np.arange(SAMPLES_PER_PACKET) * self.sample_period_s
            current_time_s = t_samples[-1] + self.sample_period_s

            # Continuous PWM waveform calculation
            # Phase: 0 to 1
            period_s = 1.0 / self.pwm_freq if self.pwm_freq > 0 else 1.0
            phase = (t_samples % period_s) / period_s
            duty_frac = self.pwm_duty / 100.0

            # Digital HIGH or LOW
            high_mask = phase < duty_frac
            v_sig = np.where(high_mask, self.v_high, self.v_low)

            # Add slight realistic noise (1-2 LSBs)
            if self.noise_amplitude > 0:
                noise = np.random.normal(0.0, self.noise_amplitude, SAMPLES_PER_PACKET)
                v_sig = np.clip(v_sig + noise, 0.0, 5.0)

            # Convert to 10-bit raw ADC count (0..1023)
            raw_adc = np.clip(np.round(v_sig * (1023.0 / 5.0)), 0, 1023).astype(np.uint16)

            # Simulated micros() timestamp at completion of buffer
            timestamp_us = int((t_samples[-1] * 1e6)) & 0xFFFFFFFF

            packet_bytes = pack_adc_packet(
                timestamp_us=timestamp_us,
                f_cpu_hz=self.f_cpu_hz,
                pwm_icr1=self.pwm_icr1,
                pwm_ocr1a=self.pwm_ocr1a,
                pwm_prescaler=self.pwm_prescaler,
                adc_ocr2a=self.adc_ocr2a,
                adc_prescaler=self.adc_prescaler,
                samples=raw_adc.tolist()
            )

            if self.on_packet_bytes and self._running:
                self.on_packet_bytes(packet_bytes)
