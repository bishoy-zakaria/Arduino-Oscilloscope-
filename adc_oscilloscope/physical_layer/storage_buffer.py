"""
Physical Layer: Thread-Safe High-Capacity Storage Ring Buffer.
Stores raw ADC and converted instantaneous voltage data.
"""

import threading
from typing import Optional, Tuple
import numpy as np


class StorageBuffer:
    """
    High-performance circular storage buffer using preallocated NumPy arrays.
    Stores continuous time, instantaneous voltage, and raw ADC samples.
    """

    def __init__(self, capacity: int = 1_000_000):
        self.capacity = int(capacity)
        self._lock = threading.Lock()

        # Preallocated linear ring buffers
        self._timestamps = np.zeros(self.capacity, dtype=np.float64)
        self._voltages = np.zeros(self.capacity, dtype=np.float32)
        self._raw_adc = np.zeros(self.capacity, dtype=np.uint16)

        self._write_pos: int = 0
        self._total_written: int = 0
        self._is_full: bool = False

        # Live metadata snapshots (updated by latest packet)
        self.latest_timestamp_us: int = 0
        self.latest_f_cpu: int = 16_000_000
        self.latest_pwm_icr1: int = 0
        self.latest_pwm_ocr1a: int = 0
        self.latest_pwm_prescaler: int = 0
        self.latest_adc_ocr2a: int = 79
        self.latest_adc_prescaler: int = 8
        self.total_packets: int = 0

    def clear(self) -> None:
        """Clear all buffered data."""
        with self._lock:
            self._write_pos = 0
            self._total_written = 0
            self._is_full = False
            self.total_packets = 0

    def append(
        self,
        timestamps: np.ndarray,
        voltages: np.ndarray,
        raw_adc: np.ndarray,
        timestamp_us: int = 0,
        f_cpu: int = 16_000_000,
        pwm_icr1: int = 0,
        pwm_ocr1a: int = 0,
        pwm_prescaler: int = 0,
        adc_ocr2a: int = 79,
        adc_prescaler: int = 8,
    ) -> None:
        """
        Appends a block of samples (e.g. 100 samples from an AdcFrame) to the buffer.
        Handles ring wrap-around efficiently.
        """
        n = len(voltages)
        if n == 0:
            return

        with self._lock:
            # Metadata update
            self.latest_timestamp_us = timestamp_us
            self.latest_f_cpu = f_cpu
            self.latest_pwm_icr1 = pwm_icr1
            self.latest_pwm_ocr1a = pwm_ocr1a
            self.latest_pwm_prescaler = pwm_prescaler
            self.latest_adc_ocr2a = adc_ocr2a
            self.latest_adc_prescaler = adc_prescaler
            self.total_packets += 1

            # Circular write
            if n >= self.capacity:
                # If chunk is larger than capacity, only take tail
                timestamps = timestamps[-self.capacity:]
                voltages = voltages[-self.capacity:]
                raw_adc = raw_adc[-self.capacity:]
                n = self.capacity

            tail = self.capacity - self._write_pos
            if n <= tail:
                self._timestamps[self._write_pos:self._write_pos + n] = timestamps
                self._voltages[self._write_pos:self._write_pos + n] = voltages
                self._raw_adc[self._write_pos:self._write_pos + n] = raw_adc
                self._write_pos += n
                if self._write_pos == self.capacity:
                    self._write_pos = 0
                    self._is_full = True
            else:
                # Wrap-around split into two copies
                self._timestamps[self._write_pos:self.capacity] = timestamps[:tail]
                self._voltages[self._write_pos:self.capacity] = voltages[:tail]
                self._raw_adc[self._write_pos:self.capacity] = raw_adc[:tail]

                rem = n - tail
                self._timestamps[:rem] = timestamps[tail:]
                self._voltages[:rem] = voltages[tail:]
                self._raw_adc[:rem] = raw_adc[tail:]
                self._write_pos = rem
                self._is_full = True

            self._total_written += n

    @property
    def total_samples(self) -> int:
        """Total number of samples written since initialization or clear."""
        with self._lock:
            return self._total_written

    @property
    def current_size(self) -> int:
        """Number of valid samples currently stored in the ring buffer."""
        with self._lock:
            return self.capacity if self._is_full else self._write_pos

    def get_latest(self, n: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Returns the latest n samples as contiguous arrays (timestamps, voltages).
        """
        with self._lock:
            total = self.capacity if self._is_full else self._write_pos
            if total == 0:
                return (np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float32))

            n = min(n, total)
            if not self._is_full:
                # Contiguous from write_pos - n to write_pos
                start = self._write_pos - n
                return (
                    self._timestamps[start:self._write_pos].copy(),
                    self._voltages[start:self._write_pos].copy(),
                )

            # Circular ring buffer case
            start = (self._write_pos - n) % self.capacity
            if start < self._write_pos:
                return (
                    self._timestamps[start:self._write_pos].copy(),
                    self._voltages[start:self._write_pos].copy(),
                )
            else:
                ts = np.concatenate((self._timestamps[start:], self._timestamps[:self._write_pos]))
                volt = np.concatenate((self._voltages[start:], self._voltages[:self._write_pos]))
                return ts, volt

    def get_new_since(
        self, last_seen_total: int, max_samples: Optional[int] = None
    ) -> Tuple[np.ndarray, np.ndarray, int]:
        """
        Retrieves newly arrived samples since `last_seen_total`.
        Returns (timestamps, voltages, new_total_count).
        If the reader fell too far behind (more than capacity), it clamps to current capacity.
        """
        with self._lock:
            current_total = self._total_written
            new_count = current_total - last_seen_total
            if new_count <= 0:
                return (np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float32), current_total)

            available = self.capacity if self._is_full else self._write_pos
            if new_count > available:
                new_count = available

            if max_samples is not None and new_count > max_samples:
                new_count = max_samples

            # Extract new_count samples ending at _write_pos
            if not self._is_full:
                start = self._write_pos - new_count
                return (
                    self._timestamps[start:self._write_pos].copy(),
                    self._voltages[start:self._write_pos].copy(),
                    current_total,
                )

            start = (self._write_pos - new_count) % self.capacity
            if start < self._write_pos:
                return (
                    self._timestamps[start:self._write_pos].copy(),
                    self._voltages[start:self._write_pos].copy(),
                    current_total,
                )
            else:
                ts = np.concatenate((self._timestamps[start:], self._timestamps[:self._write_pos]))
                volt = np.concatenate((self._voltages[start:], self._voltages[:self._write_pos]))
                return ts, volt, current_total

    def get_all(self) -> Tuple[np.ndarray, np.ndarray]:
        """Returns all valid samples currently in buffer, ordered chronologically."""
        return self.get_latest(self.capacity)

    def get_time_range(self, t_min: float, t_max: float) -> Tuple[np.ndarray, np.ndarray]:
        """
        Returns samples whose timestamps fall within [t_min, t_max].
        Useful for deep zoom in the oscilloscope.
        """
        ts_all, volt_all = self.get_all()
        if len(ts_all) == 0:
            return ts_all, volt_all

        idx = np.where((ts_all >= t_min) & (ts_all <= t_max))[0]
        return ts_all[idx], volt_all[idx]
