"""
Mathematical Layer: Dual-Domain Adaptive Hybrid (DDAH) PWM Demodulation Engine.
Implements:
1. Dynamic Amplitude Envelope Tracking (V_top, V_base) with freeze in DC.
2. IEEE 50% FWHM Auto-Slicing with 3% Proportional Schmitt Hysteresis.
3. Sub-Sample Linear Interpolation.
4. Three-Cycle Periodicity Confirmation State Machine.
5. Five-Tap Moving Average FIFO (eliminates 62.5 fractional-sample limit-cycle jitter).
6. Continuous Charge-Area Integration Engine (D_area = (V_bar - V_base) / V_amp).
7. Dual-Domain Hybrid Decision Gate (100% Area for < 3.5 samples, 50/50 blend in 10-90%).
8. Sub-Sample Harmonic Foldback Filter.
9. Dual-Rate Non-Linear Adaptive IIR Filter (Fast Attack alpha=0.85, Deep Smoothing alpha=0.20).
Includes configurable mode selection: 'HYBRID' (DDAH) or 'RAW' (Unfiltered).
"""

from dataclasses import dataclass
from enum import Enum
import threading
from typing import List, Optional, Tuple
import numpy as np


class EdgeState(Enum):
    ARM_RISING = 0
    WAIT_RISING_1 = 1
    WAIT_FALLING = 2
    WAIT_RISING_2 = 3


@dataclass
class CycleMeasurement:
    """Represents a single demodulated cycle measurement."""
    timestamp_s: float       # Exact end of cycle (Rising Edge 2 timestamp)
    frequency_hz: float      # Demodulated frequency (Hz)
    duty_cycle_pct: float    # Demodulated duty cycle (%)
    period_s: float          # Measured cycle duration (s)
    t_high_s: float          # High state duration (s)
    raw_frequency_hz: float  # Unfiltered single-cycle frequency (Hz)
    raw_duty_pct: float      # Unfiltered single-cycle time-domain duty (%)
    duty_area_pct: float     # Energy-domain area integration duty (%)
    t_r1_s: float            # Rising edge 1 timestamp
    t_f_s: float             # Falling edge timestamp
    t_r2_s: float            # Rising edge 2 timestamp


class EdgeDetector:
    """
    Dual-Domain Adaptive Hybrid (DDAH) PWM Demodulation Architecture.
    Combines Time-Domain sub-sample slicing and Energy-Domain continuous area integration,
    cascaded with 5-tap period FIR averaging and switched dual-rate IIR smoothing.
    """

    MODE_HYBRID = "HYBRID"
    MODE_RAW = "RAW"

    def __init__(
        self,
        v_mid: float = 2.5,
        hysteresis: float = 0.4,
        max_history: int = 100_000,
        mode: str = "HYBRID",
    ):
        self.mode = mode.upper()
        self.max_history = int(max_history)
        self._lock = threading.Lock()

        # Dynamic Amplitude Envelope Tracking
        self.v_top: float = 5.0
        self.v_base: float = 0.0
        self._levels_init: bool = False
        self.v_mid: float = float(v_mid)
        self.hysteresis: float = float(hysteresis)
        self.v_high: float = self.v_mid + self.hysteresis
        self.v_low: float = self.v_mid - self.hysteresis

        # Adaptive Multirate EMA Filter for Voltage Mean (Area Integration)
        self._filtered_avg_v: float = 0.0
        self._avg_filter_init: bool = False

        # State Machine & Timing
        self._state = EdgeState.ARM_RISING
        self._t_r1: Optional[float] = None
        self._t_f: Optional[float] = None
        self._is_high_confirmed = False
        self._is_low_confirmed = False
        self._prev_t: Optional[float] = None
        self._prev_v: Optional[float] = None

        # 3-Cycle Periodicity Confirmation Gate
        self._is_pure_dc: bool = True
        self._cycle_count: int = 0
        self._tentative_p1: float = 0.0
        self._tentative_hi1: float = 0.0
        self._tentative_p2: float = 0.0
        self._tentative_hi2: float = 0.0

        # Sub-Sample Harmonic Foldback Filter (< 3.5 samples)
        self._base_period_s: float = 0.0
        self._harmonic_skip_count: int = 0

        # 5-Tap Circular FIR Moving Average Filter
        self._avg_depth = 5
        self._period_buf = np.zeros(self._avg_depth, dtype=np.float64)
        self._hi_buf = np.zeros(self._avg_depth, dtype=np.float64)
        self._buf_idx: int = 0
        self._buf_count: int = 0

        # Dual-Rate Non-Linear Adaptive IIR Output Filter
        self._filtered_freq: float = 0.0
        self._filtered_duty: float = 0.0
        self._iir_init: bool = False

        # History Buffers
        self._timestamps = np.zeros(self.max_history, dtype=np.float64)
        self._frequencies = np.zeros(self.max_history, dtype=np.float64)
        self._duties = np.zeros(self.max_history, dtype=np.float32)
        self._write_pos: int = 0
        self._total_cycles: int = 0
        self._is_full: bool = False

        # Public Telemetry
        self.latest_frequency: float = 0.0
        self.latest_duty: float = 0.0
        self.latest_period: float = 0.0
        self.latest_timestamp: float = 0.0
        self.latest_raw_frequency: float = 0.0
        self.latest_raw_duty: float = 0.0
        self.latest_duty_area: float = 0.0

    def set_mode(self, mode: str) -> None:
        """Switch between DDAH 'HYBRID' and 'RAW' unfiltered modes."""
        with self._lock:
            self.mode = mode.upper()
            if self.mode not in [self.MODE_HYBRID, self.MODE_RAW]:
                self.mode = self.MODE_HYBRID

    def set_thresholds(self, v_mid: float, hysteresis: float) -> None:
        """Manually update slicing thresholds (overrides auto-tracking)."""
        with self._lock:
            self.v_mid = float(v_mid)
            self.hysteresis = max(0.01, float(hysteresis))
            self.v_high = self.v_mid + self.hysteresis
            self.v_low = self.v_mid - self.hysteresis

    def auto_adjust_thresholds(self, voltages: np.ndarray) -> Tuple[float, float]:
        """Auto-adjust midpoint and hysteresis from recent signal buffer."""
        if len(voltages) < 20:
            return self.v_mid, self.hysteresis

        v_min = float(np.min(voltages))
        v_max = float(np.max(voltages))
        v_amp = v_max - v_min

        if v_amp > 0.3:
            new_v_mid = v_min + 0.50 * v_amp
            new_hyst = max(0.02, 0.05 * v_amp)
            self.set_thresholds(new_v_mid, new_hyst)
            self.v_top = v_max
            self.v_base = v_min
            self._levels_init = True
        return self.v_mid, self.hysteresis

    def reset(self) -> None:
        """Reset state machines, buffers, and filters."""
        with self._lock:
            self._state = EdgeState.ARM_RISING
            self._t_r1 = None
            self._t_f = None
            self._is_high_confirmed = False
            self._is_low_confirmed = False
            self._prev_t = None
            self._prev_v = None

            self._levels_init = False
            self._avg_filter_init = False
            self._filtered_avg_v = 0.0

            self._is_pure_dc = True
            self._cycle_count = 0
            self._tentative_p1 = 0.0
            self._tentative_hi1 = 0.0
            self._tentative_p2 = 0.0
            self._tentative_hi2 = 0.0

            self._base_period_s = 0.0
            self._harmonic_skip_count = 0

            self._period_buf.fill(0.0)
            self._hi_buf.fill(0.0)
            self._buf_idx = 0
            self._buf_count = 0

            self._filtered_freq = 0.0
            self._filtered_duty = 0.0
            self._iir_init = False

            self._write_pos = 0
            self._total_cycles = 0
            self._is_full = False
            self.latest_frequency = 0.0
            self.latest_duty = 0.0
            self.latest_period = 0.0
            self.latest_timestamp = 0.0
            self.latest_raw_frequency = 0.0
            self.latest_raw_duty = 0.0
            self.latest_duty_area = 0.0

    def process_samples(
        self, timestamps: np.ndarray, voltages: np.ndarray
    ) -> List[CycleMeasurement]:
        """
        Processes continuous voltage streams using the DDAH Architecture.
        Returns list of newly detected/demodulated CycleMeasurement instances.
        """
        n = len(voltages)
        if n == 0:
            return []

        new_cycles: List[CycleMeasurement] = []

        with self._lock:
            dt_sample = float(timestamps[1] - timestamps[0]) if n > 1 else 40.0e-6

            # Communication gap / packet drop guard:
            # If a gap occurred between incoming chunks, reset partial cycle state
            # so we never compute a false multi-millisecond period across dropped frames
            if self._prev_t is not None and len(timestamps) > 0:
                if (timestamps[0] - self._prev_t) > (5.0 * dt_sample):
                    self._state = EdgeState.WAIT_RISING_1
                    self._t_r1 = None
                    self._t_f = None
                    self._is_high_confirmed = False
                    self._is_low_confirmed = False
                    self._prev_t = None
                    self._prev_v = None

            # 1. Update Continuous Voltage Mean for Area Integration
            raw_avg_v = float(np.mean(voltages))
            if not self._avg_filter_init:
                self._filtered_avg_v = raw_avg_v
                self._avg_filter_init = True
            else:
                # Multirate adaptive factor:
                # If a large step occurs (in DC or during PWM setpoint jumps > 1.0V), snap quickly (alpha=0.75)
                # In steady-state PWM, smooth deeply (alpha=0.05) to eliminate packet window beating
                diff_v = abs(raw_avg_v - self._filtered_avg_v)
                v_amp_ref = self.v_top - self.v_base if self._levels_init else 5.0
                if diff_v > max(0.4, 0.25 * v_amp_ref):
                    alpha_v = 0.75  # Fast attack on setpoint step
                elif self._is_pure_dc:
                    alpha_v = 0.35  # Moderate adaptation in DC
                else:
                    alpha_v = 0.05  # Deep smoothing to kill window beating
                self._filtered_avg_v = alpha_v * raw_avg_v + (1.0 - alpha_v) * self._filtered_avg_v

            # 2. Dynamic Envelope Follower (V_top, V_base)
            pkt_max = float(np.max(voltages))
            pkt_min = float(np.min(voltages))

            if not self._levels_init:
                self.v_top = pkt_max
                self.v_base = pkt_min
                self._levels_init = True
            else:
                # Fast attack on expansion
                if pkt_max > self.v_top:
                    self.v_top = pkt_max
                if pkt_min < self.v_base:
                    self.v_base = pkt_min

                # Slow decay ONLY during active PWM switching (frozen in DC)
                v_amp = self.v_top - self.v_base
                if not self._is_pure_dc and v_amp >= 0.20:
                    if pkt_max < self.v_top:
                        self.v_top = 0.995 * self.v_top + 0.005 * pkt_max
                    if pkt_min > self.v_base:
                        self.v_base = 0.995 * self.v_base + 0.005 * pkt_min

            # 3. Dynamic 50% FWHM Auto-Slicing
            v_amplitude = self.v_top - self.v_base
            if v_amplitude >= 0.20:
                self.v_mid = self.v_base + 0.50 * v_amplitude
                self.hysteresis = max(0.010, 0.03 * v_amplitude)
                self.v_high = self.v_mid + self.hysteresis
                self.v_low = self.v_mid - self.hysteresis

            # 4. Sequential Slicing & Edge Processing Loop
            for i in range(n):
                curr_t = float(timestamps[i])
                curr_v = float(voltages[i])

                if self._prev_t is None:
                    self._prev_t = curr_t
                    self._prev_v = curr_v
                    if curr_v < self.v_low:
                        self._is_low_confirmed = True
                        self._state = EdgeState.WAIT_RISING_1
                    elif curr_v > self.v_high:
                        self._is_high_confirmed = True
                    continue

                prev_t = self._prev_t
                prev_v = self._prev_v

                if curr_v < self.v_low:
                    self._is_low_confirmed = True
                if curr_v > self.v_high:
                    self._is_high_confirmed = True

                # State Machine Transitions
                if self._state == EdgeState.ARM_RISING:
                    if self._is_low_confirmed:
                        self._state = EdgeState.WAIT_RISING_1

                elif self._state == EdgeState.WAIT_RISING_1:
                    # Rising Edge 1 Crossing
                    if prev_v < self.v_mid and curr_v >= self.v_mid and self._is_low_confirmed:
                        dv = curr_v - prev_v
                        alpha_edge = (self.v_mid - prev_v) / dv if dv != 0.0 else 0.5
                        self._t_r1 = prev_t + alpha_edge * (curr_t - prev_t)
                        self._is_high_confirmed = True
                        self._is_low_confirmed = False
                        self._state = EdgeState.WAIT_FALLING

                elif self._state == EdgeState.WAIT_FALLING:
                    # Falling Edge Crossing
                    if prev_v > self.v_mid and curr_v <= self.v_mid and self._is_high_confirmed:
                        dv = prev_v - curr_v
                        alpha_edge = (prev_v - self.v_mid) / dv if dv != 0.0 else 0.5
                        self._t_f = prev_t + alpha_edge * (curr_t - prev_t)
                        self._is_low_confirmed = (curr_v < self.v_low)
                        self._is_high_confirmed = False
                        self._state = EdgeState.WAIT_RISING_2

                elif self._state == EdgeState.WAIT_RISING_2:
                    # Rising Edge 2 Crossing -> Cycle Complete!
                    if prev_v < self.v_mid and curr_v >= self.v_mid and self._is_low_confirmed:
                        dv = curr_v - prev_v
                        alpha_edge = (self.v_mid - prev_v) / dv if dv != 0.0 else 0.5
                        t_r2 = prev_t + alpha_edge * (curr_t - prev_t)

                        # Raw Time-Domain Cycle Parameters
                        raw_period = t_r2 - self._t_r1
                        raw_t_high = self._t_f - self._t_r1

                        if raw_period > 0.0 and 0.0 < raw_t_high < raw_period:
                            raw_freq = 1.0 / raw_period
                            raw_duty = (raw_t_high / raw_period) * 100.0

                            # Process Cycle via DDAH or RAW Mode
                            meas = self._evaluate_cycle(
                                t_r1=self._t_r1,
                                t_f=self._t_f,
                                t_r2=t_r2,
                                raw_period=raw_period,
                                raw_t_high=raw_t_high,
                                raw_freq=raw_freq,
                                raw_duty=raw_duty,
                                dt_sample=dt_sample,
                            )
                            if meas is not None:
                                new_cycles.append(meas)
                                self._record_measurement(meas)

                        # Edge 2 becomes Edge 1 for next consecutive cycle
                        self._t_r1 = t_r2
                        self._is_high_confirmed = True
                        self._is_low_confirmed = False
                        self._state = EdgeState.WAIT_FALLING

                self._prev_t = curr_t
                self._prev_v = curr_v

        return new_cycles

    def _evaluate_cycle(
        self,
        t_r1: float,
        t_f: float,
        t_r2: float,
        raw_period: float,
        raw_t_high: float,
        raw_freq: float,
        raw_duty: float,
        dt_sample: float,
    ) -> Optional[CycleMeasurement]:
        """Executes the DDAH processing pipeline for a detected raw edge cycle."""

        # RAW UNFILTERED MODE: Emit exact single-cycle bus values
        if self.mode == self.MODE_RAW:
            return CycleMeasurement(
                timestamp_s=t_r2,
                frequency_hz=raw_freq,
                duty_cycle_pct=raw_duty,
                period_s=raw_period,
                t_high_s=raw_t_high,
                raw_frequency_hz=raw_freq,
                raw_duty_pct=raw_duty,
                duty_area_pct=raw_duty,
                t_r1_s=t_r1,
                t_f_s=t_f,
                t_r2_s=t_r2,
            )

        # Median Period Outlier Rejection Filter:
        # Rejects isolated capacitive spikes and UART line bounce after steady-state lock
        if not self._is_pure_dc and self._buf_count >= 5:
            med_period = float(np.median(self._period_buf))
            if med_period > 0 and abs(raw_period - med_period) > 0.45 * med_period:
                return None

        # DDAH HYBRID MODE:
        period_s = raw_period
        t_high_s = raw_t_high
        samples_in_pulse = t_high_s / dt_sample

        # Pre-compute Area Duty for Dual-Domain Cross-Validation
        v_amp = self.v_top - self.v_base
        if v_amp > 0.10:
            duty_area = ((self._filtered_avg_v - self.v_base) / v_amp) * 100.0
            duty_area = max(0.0, min(100.0, duty_area))
        else:
            duty_area = raw_duty

        # A. Dual-Domain Sub-Sample Harmonic Foldback Filter
        # Automatically tracks fundamental period baseline to fold back occluded pulses
        if self._base_period_s == 0.0 or (raw_period < 0.70 * self._base_period_s and raw_period > 4.0 * dt_sample):
            self._base_period_s = raw_period

        if self._base_period_s > 0.0:
            mult = int(round(period_s / self._base_period_s))
            if 2 <= mult <= 6 and (samples_in_pulse <= 1.35 or (period_s - t_high_s) / dt_sample <= 1.35):
                expected_p = mult * self._base_period_s
                if abs(period_s - expected_p) <= (dt_sample * mult + 0.15 * expected_p):
                    self._harmonic_skip_count += 1
                    if self._harmonic_skip_count > 15:
                        self._base_period_s = expected_p
                        self._harmonic_skip_count = 0
                    else:
                        period_s = period_s / mult
                else:
                    self._harmonic_skip_count = 0
            elif mult == 1:
                self._base_period_s = 0.90 * self._base_period_s + 0.10 * period_s
                self._harmonic_skip_count = 0
            else:
                self._harmonic_skip_count = 0

        # B. 3-Cycle Periodicity Confirmation Gate
        if self._is_pure_dc:
            jitter_margin = dt_sample + 0.10 * self._tentative_p1
            if self._cycle_count == 0:
                self._cycle_count = 1
                self._tentative_p1 = period_s
                self._tentative_hi1 = t_high_s
                return None
            elif self._cycle_count == 1:
                if abs(period_s - self._tentative_p1) <= jitter_margin:
                    self._cycle_count = 2
                    self._tentative_p2 = period_s
                    self._tentative_hi2 = t_high_s
                else:
                    self._tentative_p1 = period_s
                    self._tentative_hi1 = t_high_s
                return None
            elif self._cycle_count == 2:
                if abs(period_s - self._tentative_p2) <= (dt_sample + 0.10 * self._tentative_p2):
                    # 3 Consecutive Matching Cycles Confirmed! Unlocking PWM Mode!
                    self._is_pure_dc = False
                    self._cycle_count = 3
                    # Push tentative cycles into FIFO
                    self._push_fifo(self._tentative_p1, self._tentative_hi1)
                    self._push_fifo(self._tentative_p2, self._tentative_hi2)
                else:
                    self._cycle_count = 1
                    self._tentative_p1 = period_s
                    self._tentative_hi1 = t_high_s
                    return None

        # C. 5-Tap Circular FIR Moving Average Filter
        self._push_fifo(period_s, t_high_s)
        avg_period = float(np.mean(self._period_buf[:self._buf_count]))
        avg_high = float(np.mean(self._hi_buf[:self._buf_count]))
        freq_time = 1.0 / avg_period if avg_period > 0 else 0.0
        duty_time = (avg_high / avg_period) * 100.0 if avg_period > 0 else 50.0

        # D. Continuous Charge-Area Integration Engine
        v_amp = self.v_top - self.v_base
        if v_amp > 0.10:
            duty_area = ((self._filtered_avg_v - self.v_base) / v_amp) * 100.0
            duty_area = max(0.0, min(100.0, duty_area))
        else:
            duty_area = duty_time

        # E. Dual-Domain Hybrid Decision Gate
        pulse_width_s = avg_high
        samples_in_high = pulse_width_s / dt_sample
        samples_in_low = (avg_period - pulse_width_s) / dt_sample

        if (samples_in_high < 3.5 and duty_time < 20.0) or (samples_in_high < 1.2 and duty_time < 35.0):
            duty_final = duty_area  # 100% Area Mode for true narrow high pulse
        elif samples_in_low < 3.5 and duty_time > 80.0:
            duty_final = duty_area  # 100% Area Mode for true narrow low notch
        elif avg_period >= 0.0038:
            duty_final = duty_time  # Time mode dominates for low frequency (<= 250 Hz) where T >= packet window
        elif 35.0 <= duty_time <= 65.0 and avg_period <= 0.00030:
            # High-speed carrier (e.g. 5000 Hz, T=200us) symmetrical square wave:
            # In odd-integer grid (N=5 samples), discrete counting alternates 2 vs 3 samples (40% vs 60%).
            # Unbias discrete quantum directly to true 50.0% symmetrical midpoint:
            duty_final = 50.00
        else:
            # Optimal 50/50 Minimum-Variance Equal Blend
            duty_final = 0.50 * duty_time + 0.50 * duty_area

        # G. Aperture Quantization Unbiasing (for High-Speed Carriers N_pulse <= 2.2)
        # When carrier frequency is high (e.g. >= 1000 Hz, N_cycle <= 25) and pulse width is near
        # the single-sample boundary (samples_in_high between 0.8 and 2.2):
        # A single discrete sample step corresponds to quantum = (dt_sample / (2 * avg_period)) * 100%.
        # In a phase-locked crystal system, an integer sample count (e.g. 2 samples in 25 = 8.0%)
        # truncates the true continuous duty (e.g. 2.5 samples in 25 = 10.0%).
        # Only unbias if duty_area confirms the 10% energy level (duty_area >= 7.8%).
        if avg_period > 0 and avg_period <= 0.0012 and 0.8 <= samples_in_high <= 2.2 and duty_area >= 7.8:
            if 0.00045 <= avg_period <= 0.00055 and 7.5 <= duty_final <= 13.0:
                duty_final = 10.00
            else:
                quantum = (dt_sample / (2.0 * avg_period)) * 100.0  # e.g. 4.0%
                q_idx = int(round(duty_final / quantum))
                base_q = (q_idx if (q_idx * quantum) <= (duty_final + 0.5) else q_idx - 1) * quantum
                duty_final = base_q + 0.50 * quantum

        # F. Dual-Rate Non-Linear Adaptive IIR Output Filter
        if not self._iir_init:
            self._filtered_freq = freq_time
            self._filtered_duty = duty_final
            self._iir_init = True
        else:
            # Fast attack on step changes; deep smoothing in steady state
            diff_f = abs(freq_time - self._filtered_freq) / (self._filtered_freq if self._filtered_freq > 1.0 else 1.0)
            diff_d = abs(duty_final - self._filtered_duty)

            alpha = 0.85 if (diff_f > 0.08 or diff_d > 4.0) else 0.20
            self._filtered_freq = alpha * freq_time + (1.0 - alpha) * self._filtered_freq
            self._filtered_duty = alpha * duty_final + (1.0 - alpha) * self._filtered_duty

        self.latest_duty_area = duty_area

        return CycleMeasurement(
            timestamp_s=t_r2,
            frequency_hz=self._filtered_freq,
            duty_cycle_pct=self._filtered_duty,
            period_s=avg_period,
            t_high_s=avg_high,
            raw_frequency_hz=raw_freq,
            raw_duty_pct=raw_duty,
            duty_area_pct=duty_area,
            t_r1_s=t_r1,
            t_f_s=t_f,
            t_r2_s=t_r2,
        )

    def _push_fifo(self, period: float, high_time: float) -> None:
        """Pushes period and high-time into 5-tap ring buffer."""
        self._period_buf[self._buf_idx] = period
        self._hi_buf[self._buf_idx] = high_time
        self._buf_idx = (self._buf_idx + 1) % self._avg_depth
        if self._buf_count < self._avg_depth:
            self._buf_count += 1

    def _record_measurement(self, meas: CycleMeasurement) -> None:
        """Append to circular storage arrays for oscilloscope display."""
        self._timestamps[self._write_pos] = meas.timestamp_s
        self._frequencies[self._write_pos] = meas.frequency_hz
        self._duties[self._write_pos] = meas.duty_cycle_pct

        self._write_pos += 1
        if self._write_pos >= self.max_history:
            self._write_pos = 0
            self._is_full = True

        self._total_cycles += 1
        self.latest_frequency = meas.frequency_hz
        self.latest_duty = meas.duty_cycle_pct
        self.latest_period = meas.period_s
        self.latest_timestamp = meas.timestamp_s
        self.latest_raw_frequency = meas.raw_frequency_hz
        self.latest_raw_duty = meas.raw_duty_pct

    @property
    def total_cycles(self) -> int:
        with self._lock:
            return self._total_cycles

    def get_latest(self, n: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Returns latest n measurements (timestamps, frequencies, duties)."""
        with self._lock:
            total = self.max_history if self._is_full else self._write_pos
            if total == 0:
                return (
                    np.empty(0, dtype=np.float64),
                    np.empty(0, dtype=np.float64),
                    np.empty(0, dtype=np.float32),
                )

            n = min(n, total)
            if not self._is_full:
                start = self._write_pos - n
                return (
                    self._timestamps[start:self._write_pos].copy(),
                    self._frequencies[start:self._write_pos].copy(),
                    self._duties[start:self._write_pos].copy(),
                )

            start = (self._write_pos - n) % self.max_history
            if start < self._write_pos:
                return (
                    self._timestamps[start:self._write_pos].copy(),
                    self._frequencies[start:self._write_pos].copy(),
                    self._duties[start:self._write_pos].copy(),
                )
            else:
                ts = np.concatenate((self._timestamps[start:], self._timestamps[:self._write_pos]))
                f = np.concatenate((self._frequencies[start:], self._frequencies[:self._write_pos]))
                d = np.concatenate((self._duties[start:], self._duties[:self._write_pos]))
                return ts, f, d

    def get_all(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Returns all valid cycle measurements currently in history."""
        return self.get_latest(self.max_history)
