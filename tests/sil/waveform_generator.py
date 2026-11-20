"""
SiL Signal Generator: Synthesizes standardized analog waveforms and encapsulates
them into exact 25 kSPS binary UART frames matching arduinoUNO_ADC.ino.
Compliant with IEEE 181-2011 (Transitions, Pulses, and Related Waveforms) and ISO 16750-2.
"""

from typing import List, Tuple
import numpy as np

from adc_oscilloscope.physical_layer.packet_parser import (
    pack_adc_packet,
    SAMPLES_PER_PACKET,
)


class SilWaveformGenerator:
    """
    Generates precision test signals and serializes them into 25 kSPS binary UART packets.
    """

    def __init__(self, fs: float = 25000.0, vref: float = 5.0, f_cpu: int = 16_000_000):
        self.fs = float(fs)
        self.dt = 1.0 / self.fs  # 40.0 us
        self.vref = float(vref)
        self.f_cpu = int(f_cpu)
        self.adc_ocr2a = 79
        self.adc_prescaler = 8

    def generate_square(
        self,
        duration_s: float,
        freq_hz: float,
        duty_pct: float,
        v_high: float = 4.95,
        v_low: float = 0.05,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generates an ideal square wave per IEEE 181-2011."""
        num_samples = int(round(duration_s * self.fs))
        t = np.arange(num_samples, dtype=np.float64) * self.dt
        period = 1.0 / max(0.001, freq_hz)
        phase = (t % period) / period
        high_fraction = max(0.0, min(1.0, duty_pct / 100.0))
        voltages = np.where(phase < high_fraction, v_high, v_low).astype(np.float32)
        return t, voltages

    def generate_trapezoidal(
        self,
        duration_s: float,
        freq_hz: float,
        duty_pct: float,
        t_rise_s: float = 20.0e-6,
        t_fall_s: float = 20.0e-6,
        v_high: float = 4.90,
        v_low: float = 0.10,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Generates a trapezoidal wave with linear transition ramps per IEEE 181-2011.
        Evaluates continuous time at high resolution before sampling at 25 kSPS.
        """
        # Oversample by 20x to capture exact analog ramp physics, then downsample to 25 kSPS
        oversample = 20
        fs_high = self.fs * oversample
        dt_high = 1.0 / fs_high
        num_samples_hi = int(round(duration_s * fs_high))
        t_hi = np.arange(num_samples_hi, dtype=np.float64) * dt_high

        period = 1.0 / max(0.001, freq_hz)
        phase_time = t_hi % period

        t_high_duration = period * (duty_pct / 100.0)
        t_plateau = max(0.0, t_high_duration - 0.5 * (t_rise_s + t_fall_s))

        v_amp = v_high - v_low
        v_hi = np.full(num_samples_hi, v_low, dtype=np.float32)

        for i, pt in enumerate(phase_time):
            if pt < t_rise_s:
                # Rising ramp
                v_hi[i] = v_low + (pt / max(1e-9, t_rise_s)) * v_amp
            elif pt < (t_rise_s + t_plateau):
                # High plateau
                v_hi[i] = v_high
            elif pt < (t_rise_s + t_plateau + t_fall_s):
                # Falling ramp
                elapsed_fall = pt - (t_rise_s + t_plateau)
                v_hi[i] = v_high - (elapsed_fall / max(1e-9, t_fall_s)) * v_amp
            else:
                # Low baseline
                v_hi[i] = v_low

        # Downsample to 25 kSPS
        t = t_hi[::oversample]
        voltages = v_hi[::oversample]
        return t, voltages

    def generate_sine(
        self,
        duration_s: float,
        freq_hz: float,
        v_offset: float = 2.50,
        v_amplitude: float = 2.40,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generates a sinusoidal continuous zero-crossing test wave."""
        num_samples = int(round(duration_s * self.fs))
        t = np.arange(num_samples, dtype=np.float64) * self.dt
        voltages = (v_offset + v_amplitude * np.sin(2.0 * np.pi * freq_hz * t)).astype(np.float32)
        return t, np.clip(voltages, 0.0, self.vref)

    def generate_triangular(
        self,
        duration_s: float,
        freq_hz: float,
        v_low: float = 0.20,
        v_high: float = 4.80,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generates a symmetric triangular wave (linear ramp crossing)."""
        num_samples = int(round(duration_s * self.fs))
        t = np.arange(num_samples, dtype=np.float64) * self.dt
        period = 1.0 / max(0.001, freq_hz)
        phase = (t % period) / period
        v_amp = v_high - v_low
        tri = np.where(phase < 0.5, 2.0 * phase, 2.0 * (1.0 - phase))
        voltages = (v_low + tri * v_amp).astype(np.float32)
        return t, voltages

    def generate_pure_dc(
        self, duration_s: float, v_level: float = 5.0
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generates a pure flat DC signal (testing 0 Hz, DC hold FSM)."""
        num_samples = int(round(duration_s * self.fs))
        t = np.arange(num_samples, dtype=np.float64) * self.dt
        voltages = np.full(num_samples, float(v_level), dtype=np.float32)
        return t, voltages

    def generate_dc_to_pwm(
        self,
        dc_duration_s: float,
        pwm_duration_s: float,
        freq_hz: float,
        duty_pct: float,
        v_dc: float = 0.05,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generates a cold-start transition: Pure DC followed by active PWM."""
        t_dc, v_dc_arr = self.generate_pure_dc(dc_duration_s, v_dc)
        t_pwm, v_pwm_arr = self.generate_square(pwm_duration_s, freq_hz, duty_pct)

        t_total = np.concatenate([t_dc, t_dc[-1] + self.dt + t_pwm])
        v_total = np.concatenate([v_dc_arr, v_pwm_arr])
        return t_total, v_total

    def generate_pwm_to_dc(
        self,
        pwm_duration_s: float,
        dc_duration_s: float,
        freq_hz: float,
        duty_pct: float,
        v_dc: float = 4.95,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generates a cutoff transition: Active PWM followed by a pure DC hold."""
        t_pwm, v_pwm_arr = self.generate_square(pwm_duration_s, freq_hz, duty_pct)
        t_dc, v_dc_arr = self.generate_pure_dc(dc_duration_s, v_dc)

        t_total = np.concatenate([t_pwm, t_pwm[-1] + self.dt + t_dc])
        v_total = np.concatenate([v_pwm_arr, v_dc_arr])
        return t_total, v_total

    def generate_duty_step(
        self,
        duration1_s: float,
        duration2_s: float,
        freq_hz: float,
        duty1_pct: float,
        duty2_pct: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generates an instantaneous duty cycle step (testing IIR fast-attack mode)."""
        t1, v1 = self.generate_square(duration1_s, freq_hz, duty1_pct)
        t2, v2 = self.generate_square(duration2_s, freq_hz, duty2_pct)

        t_total = np.concatenate([t1, t1[-1] + self.dt + t2])
        v_total = np.concatenate([v1, v2])
        return t_total, v_total

    def generate_freq_step(
        self,
        duration1_s: float,
        duration2_s: float,
        freq1_hz: float,
        freq2_hz: float,
        duty_pct: float,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generates an instantaneous carrier frequency step."""
        t1, v1 = self.generate_square(duration1_s, freq1_hz, duty_pct)
        t2, v2 = self.generate_square(duration2_s, freq2_hz, duty_pct)

        t_total = np.concatenate([t1, t1[-1] + self.dt + t2])
        v_total = np.concatenate([v1, v2])
        return t_total, v_total

    def add_disturbances(
        self,
        voltages: np.ndarray,
        t: np.ndarray,
        noise_rms_v: float = 0.0,
        mains_hum_amp_v: float = 0.0,
        dc_drift_v: float = 0.0,
    ) -> np.ndarray:
        """Adds Gaussian noise, 50 Hz power-line hum, and DC baseline drift per ISO 16750-2."""
        out = voltages.copy()
        n = len(out)

        if noise_rms_v > 0.0:
            out += np.random.normal(0.0, noise_rms_v, n).astype(np.float32)

        if mains_hum_amp_v > 0.0:
            out += (mains_hum_amp_v * np.sin(2.0 * np.pi * 50.0 * t)).astype(np.float32)

        if dc_drift_v != 0.0:
            ramp = np.linspace(0.0, dc_drift_v, n, dtype=np.float32)
            out += ramp

        return np.clip(out, 0.0, self.vref)

    def serialize_to_uart_stream(
        self,
        t: np.ndarray,
        voltages: np.ndarray,
        freq_hz: float = 400.0,
        duty_pct: float = 50.0,
    ) -> bytes:
        """
        Converts simulated voltages into the exact binary UART byte stream
        emitted by arduinoUNO_ADC.ino (0xAA 0x55 + 217-byte payload).
        """
        raw_adc = np.clip(np.round(voltages * (1023.0 / self.vref)), 0, 1023).astype(np.uint16)
        n_samples = len(raw_adc)

        # Compute Timer1 register telemetry matching target frequency and duty
        f_cpu = self.f_cpu
        psc = 1
        for candidate_psc in [1, 8, 64, 256, 1024]:
            top = (float(f_cpu) / (float(candidate_psc) * max(1.0, freq_hz))) - 1.0
            if 1.0 <= top <= 65535.0:
                psc = candidate_psc
                break
        icr1 = int(round((float(f_cpu) / (float(psc) * max(1.0, freq_hz))) - 1.0))
        icr1 = max(1, min(65535, icr1))
        ocr1a = int(round((duty_pct / 100.0) * (icr1 + 1)))

        stream = bytearray()
        num_packets = n_samples // SAMPLES_PER_PACKET

        for p_idx in range(num_packets):
            chunk = raw_adc[p_idx * SAMPLES_PER_PACKET : (p_idx + 1) * SAMPLES_PER_PACKET]
            end_t_s = t[(p_idx + 1) * SAMPLES_PER_PACKET - 1]
            timestamp_us = int(round(end_t_s * 1.0e6)) & 0xFFFFFFFF

            packet_bytes = pack_adc_packet(
                timestamp_us=timestamp_us,
                f_cpu_hz=self.f_cpu,
                pwm_icr1=icr1,
                pwm_ocr1a=ocr1a,
                pwm_prescaler=psc,
                adc_ocr2a=self.adc_ocr2a,
                adc_prescaler=self.adc_prescaler,
                samples=chunk.tolist(),
            )
            stream.extend(packet_bytes)

        return bytes(stream)
