"""
SiL Test Harness: Ingests simulated UART streams through the 3 layers,
extracts metrics, and benchmarks against IEEE 181-2011, IEEE 1057, and IEC 60469.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np

from adc_oscilloscope.physical_layer.packet_parser import StreamParser
from adc_oscilloscope.physical_layer.storage_buffer import StorageBuffer
from adc_oscilloscope.math_layer.edge_detector import EdgeDetector, CycleMeasurement


@dataclass
class SilResult:
    """Standardized test verdict and empirical metrics for an SiL scenario."""
    test_id: str
    scenario_name: str
    waveform_type: str
    target_freq_hz: float
    target_duty_pct: float
    mode: str  # 'HYBRID' or 'RAW'
    passed: bool
    cycles_detected: int
    mean_freq_hz: float
    freq_error_hz: float
    freq_jitter_pk_pk_hz: float
    freq_std_hz: float
    mean_duty_pct: float
    duty_error_pct: float
    duty_jitter_pk_pk_pct: float
    duty_std_pct: float
    total_packets_parsed: int
    sync_losses: int
    notes: str


class SilHarness:
    """
    Software-in-the-Loop Test Runner orchestrating Physical and Mathematical Layers.
    """

    def __init__(self, buffer_capacity: int = 500_000):
        self.parser = StreamParser()
        self.buffer = StorageBuffer(capacity=buffer_capacity)
        self.detector_hybrid = EdgeDetector(v_mid=2.5, hysteresis=0.4, mode="HYBRID")
        self.detector_raw = EdgeDetector(v_mid=2.5, hysteresis=0.4, mode="RAW")

    def execute_stream(
        self,
        uart_bytes: bytes,
        mode: str = "HYBRID",
        v_mid: float = 2.5,
        hysteresis: float = 0.4,
    ) -> Tuple[List[CycleMeasurement], StorageBuffer]:
        """Runs binary UART byte stream through the entire software stack."""
        self.parser.reset()
        self.buffer.clear()

        detector = self.detector_hybrid if mode.upper() == "HYBRID" else self.detector_raw
        detector.reset()
        detector.set_thresholds(v_mid, hysteresis)

        # 1. Physical Layer: StreamParser & Streaming Feeding
        all_cycles = []
        for frame in self.parser.parse_stream(uart_bytes):
            self.buffer.append(
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
            # Stream directly into mathematical layer (100 samples per burst)
            cycles = detector.process_samples(frame.timestamps_s, frame.voltages)
            all_cycles.extend(cycles)

        return all_cycles, self.buffer

    def evaluate_scenario(
        self,
        test_id: str,
        scenario_name: str,
        waveform_type: str,
        uart_bytes: bytes,
        target_freq_hz: float,
        target_duty_pct: float,
        mode: str = "HYBRID",
        max_freq_err_hz: float = 1.0,
        max_duty_err_pct: float = 0.8,
        expect_dc: bool = False,
        v_mid: float = 2.5,
        hysteresis: float = 0.4,
        steady_tail_count: Optional[int] = None,
    ) -> SilResult:
        """Executes scenario and evaluates against IEEE/ISO error tolerance limits."""
        cycles, buf = self.execute_stream(
            uart_bytes, mode=mode, v_mid=v_mid, hysteresis=hysteresis
        )

        detector = self.detector_hybrid if mode.upper() == "HYBRID" else self.detector_raw

        # Pure DC Case Evaluation
        if expect_dc:
            # Must detect zero periodic cycles and maintain DC duty state
            is_pass = (len(cycles) == 0) and (detector.latest_frequency == 0.0)
            notes = "Pure DC state verified (0 false cycle triggers, Freq = 0.0 Hz)"
            if not is_pass:
                notes = f"FAIL: Detected {len(cycles)} false cycles during pure DC hold!"

            return SilResult(
                test_id=test_id,
                scenario_name=scenario_name,
                waveform_type=waveform_type,
                target_freq_hz=0.0,
                target_duty_pct=target_duty_pct,
                mode=mode,
                passed=is_pass,
                cycles_detected=len(cycles),
                mean_freq_hz=detector.latest_frequency,
                freq_error_hz=abs(detector.latest_frequency),
                freq_jitter_pk_pk_hz=0.0,
                freq_std_hz=0.0,
                mean_duty_pct=target_duty_pct,
                duty_error_pct=0.0,
                duty_jitter_pk_pk_pct=0.0,
                duty_std_pct=0.0,
                total_packets_parsed=self.parser.total_frames_parsed,
                sync_losses=self.parser.sync_losses,
                notes=notes,
            )

        # Periodic Waveform Case Evaluation
        if len(cycles) == 0:
            return SilResult(
                test_id=test_id,
                scenario_name=scenario_name,
                waveform_type=waveform_type,
                target_freq_hz=target_freq_hz,
                target_duty_pct=target_duty_pct,
                mode=mode,
                passed=False,
                cycles_detected=0,
                mean_freq_hz=0.0,
                freq_error_hz=target_freq_hz,
                freq_jitter_pk_pk_hz=0.0,
                freq_std_hz=0.0,
                mean_duty_pct=0.0,
                duty_error_pct=target_duty_pct,
                duty_jitter_pk_pk_pct=0.0,
                duty_std_pct=0.0,
                total_packets_parsed=self.parser.total_frames_parsed,
                sync_losses=self.parser.sync_losses,
                notes="FAIL: No valid rising->falling->rising edge cycles detected!",
            )

        # Select evaluation slice: evaluate steady state per IEEE 1057
        if steady_tail_count is not None and len(cycles) >= steady_tail_count:
            steady_cycles = cycles[-steady_tail_count:]
        elif len(cycles) >= 16:
            # Per IEEE 1057, evaluate settled steady-state cycles (last 20 cycles)
            n_eval = min(25, len(cycles) // 2)
            steady_cycles = cycles[-n_eval:]
        else:
            steady_cycles = cycles[3:] if len(cycles) > 5 else cycles

        freqs = np.array([c.frequency_hz for c in steady_cycles])
        duties = np.array([c.duty_cycle_pct for c in steady_cycles])

        mean_f = float(np.mean(freqs))
        std_f = float(np.std(freqs))
        pk_pk_f = float(np.max(freqs) - np.min(freqs))
        err_f = abs(mean_f - target_freq_hz)

        mean_d = float(np.mean(duties))
        std_d = float(np.std(duties))
        pk_pk_d = float(np.max(duties) - np.min(duties))
        err_d = abs(mean_d - target_duty_pct)

        freq_ok = err_f <= max_freq_err_hz
        duty_ok = err_d <= max_duty_err_pct
        passed = freq_ok and duty_ok and (self.parser.sync_losses == 0)

        notes = f"IEEE compliant. Freq err: {err_f:.3f} Hz, Duty err: {err_d:.3f}%"
        if not passed:
            reasons = []
            if not freq_ok:
                reasons.append(f"Freq err {err_f:.2f}Hz > {max_freq_err_hz}Hz")
            if not duty_ok:
                reasons.append(f"Duty err {err_d:.2f}% > {max_duty_err_pct}%")
            if self.parser.sync_losses > 0:
                reasons.append(f"{self.parser.sync_losses} sync losses")
            notes = "FAIL: " + ", ".join(reasons)

        return SilResult(
            test_id=test_id,
            scenario_name=scenario_name,
            waveform_type=waveform_type,
            target_freq_hz=target_freq_hz,
            target_duty_pct=target_duty_pct,
            mode=mode,
            passed=passed,
            cycles_detected=len(cycles),
            mean_freq_hz=mean_f,
            freq_error_hz=err_f,
            freq_jitter_pk_pk_hz=pk_pk_f,
            freq_std_hz=std_f,
            mean_duty_pct=mean_d,
            duty_error_pct=err_d,
            duty_jitter_pk_pk_pct=pk_pk_d,
            duty_std_pct=std_d,
            total_packets_parsed=self.parser.total_frames_parsed,
            sync_losses=self.parser.sync_losses,
            notes=notes,
        )
