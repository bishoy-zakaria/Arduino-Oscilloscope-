"""
Software-in-the-Loop (SiL) Test Suite Runner.
Executes standardized scenarios per IEEE 181-2011, IEEE 1057, and ISO 16750-2.
"""

import os
import sys
import time
from typing import List

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tests.sil.waveform_generator import SilWaveformGenerator
from tests.sil.sil_harness import SilHarness, SilResult


def run_all_sil_tests() -> List[SilResult]:
    gen = SilWaveformGenerator(fs=25000.0, vref=5.0)
    harness = SilHarness()
    results: List[SilResult] = []

    print("==========================================================================================")
    print("       SOFTWARE-IN-THE-LOOP (SiL) TEST EXECUTION: IEEE 181 / IEEE 1057 / ISO 16750-2")
    print("==========================================================================================")

    # 1A: Square Nominal
    t, v = gen.generate_square(0.25, 400.0, 50.0)
    bytes_data = gen.serialize_to_uart_stream(t, v, 400.0, 50.0)
    res = harness.evaluate_scenario("SIL-01A", "Nominal Square Wave (400 Hz, 50%)", "Square (Ideal)", bytes_data, 400.0, 50.0, max_freq_err_hz=0.5, max_duty_err_pct=0.7)
    results.append(res)

    # 1B: Trapezoidal Slew
    t, v = gen.generate_trapezoidal(0.25, 400.0, 50.0, t_rise_s=25e-6, t_fall_s=25e-6)
    bytes_data = gen.serialize_to_uart_stream(t, v, 400.0, 50.0)
    res = harness.evaluate_scenario("SIL-01B", "Trapezoidal Slew (25 us Ramps)", "Trapezoidal (IEEE 181)", bytes_data, 400.0, 50.0, max_freq_err_hz=0.6, max_duty_err_pct=0.6)
    results.append(res)

    # 1C: Sinusoidal
    t, v = gen.generate_sine(0.25, 400.0, v_offset=2.5, v_amplitude=2.3)
    bytes_data = gen.serialize_to_uart_stream(t, v, 400.0, 50.0)
    res = harness.evaluate_scenario("SIL-01C", "Sinusoidal Wave (400 Hz)", "Sine Wave (Continuous)", bytes_data, 400.0, 50.0, max_freq_err_hz=0.8, max_duty_err_pct=1.0)
    results.append(res)

    # 1D: Triangular
    t, v = gen.generate_triangular(0.25, 200.0)
    bytes_data = gen.serialize_to_uart_stream(t, v, 200.0, 50.0)
    res = harness.evaluate_scenario("SIL-01D", "Triangular Wave (200 Hz)", "Triangular (Linear)", bytes_data, 200.0, 50.0, max_freq_err_hz=0.8, max_duty_err_pct=1.0)
    results.append(res)

    # 2A: Ultra-Low Duty (2.0%)
    t, v = gen.generate_square(0.30, 400.0, 2.0)
    bytes_data = gen.serialize_to_uart_stream(t, v, 400.0, 2.0)
    res = harness.evaluate_scenario("SIL-02A", "Ultra-Low Duty (2.0%)", "Square (Micro-Pulse)", bytes_data, 400.0, 2.0, max_freq_err_hz=1.0, max_duty_err_pct=0.8)
    results.append(res)

    # 2B: Ultra-High Duty (95.0%)
    t, v = gen.generate_square(0.30, 400.0, 95.0)
    bytes_data = gen.serialize_to_uart_stream(t, v, 400.0, 95.0)
    res = harness.evaluate_scenario("SIL-02B", "Ultra-High Duty (95.0%)", "Square (Narrow Notch)", bytes_data, 400.0, 95.0, max_freq_err_hz=1.0, max_duty_err_pct=0.8)
    results.append(res)

    # 3A: Low Frequency (10 Hz)
    t, v = gen.generate_square(0.80, 10.0, 40.0)
    bytes_data = gen.serialize_to_uart_stream(t, v, 10.0, 40.0)
    res = harness.evaluate_scenario("SIL-03A", "Low Frequency (10 Hz)", "Square (Abundant)", bytes_data, 10.0, 40.0, max_freq_err_hz=0.2, max_duty_err_pct=0.5)
    results.append(res)

    # 3B: High Frequency (1000 Hz)
    t, v = gen.generate_square(0.25, 1000.0, 50.0)
    bytes_data = gen.serialize_to_uart_stream(t, v, 1000.0, 50.0)
    res = harness.evaluate_scenario("SIL-03B", "High Frequency (1000 Hz)", "Square (Sparse)", bytes_data, 1000.0, 50.0, max_freq_err_hz=2.0, max_duty_err_pct=2.0)
    results.append(res)

    # 4A: Pure DC High
    t, v = gen.generate_pure_dc(0.30, v_level=4.95)
    bytes_data = gen.serialize_to_uart_stream(t, v, 0.0, 100.0)
    res = harness.evaluate_scenario("SIL-04A", "Pure DC High Hold (5.0 V)", "DC Plateau", bytes_data, 0.0, 100.0, expect_dc=True)
    results.append(res)

    # 4B: Pure DC Low
    t, v = gen.generate_pure_dc(0.30, v_level=0.05)
    bytes_data = gen.serialize_to_uart_stream(t, v, 0.0, 0.0)
    res = harness.evaluate_scenario("SIL-04B", "Pure DC Low Hold (0.0 V)", "DC Baseline", bytes_data, 0.0, 0.0, expect_dc=True)
    results.append(res)

    # 4C: Cold-Start (DC -> PWM)
    t, v = gen.generate_dc_to_pwm(0.15, 0.25, 400.0, 50.0)
    bytes_data = gen.serialize_to_uart_stream(t, v, 400.0, 50.0)
    res = harness.evaluate_scenario("SIL-04C", "Cold-Start (DC -> PWM)", "Transition", bytes_data, 400.0, 50.0, max_freq_err_hz=1.0, max_duty_err_pct=1.0, steady_tail_count=15)
    results.append(res)

    # 5A: Duty Step (20% -> 80%)
    t, v = gen.generate_duty_step(0.20, 0.25, 400.0, 20.0, 80.0)
    bytes_data = gen.serialize_to_uart_stream(t, v, 400.0, 80.0)
    res = harness.evaluate_scenario("SIL-05A", "Duty Step (20% -> 80%)", "Step Function", bytes_data, 400.0, 80.0, max_freq_err_hz=1.0, max_duty_err_pct=1.8, steady_tail_count=15)
    results.append(res)

    # 6A: Disturbances
    t, v = gen.generate_square(0.30, 400.0, 50.0)
    v_dist = gen.add_disturbances(v, t, noise_rms_v=0.04, mains_hum_amp_v=0.08, dc_drift_v=0.15)
    bytes_data = gen.serialize_to_uart_stream(t, v_dist, 400.0, 50.0)
    res = harness.evaluate_scenario("SIL-06A", "ISO 16750-2 Disturbance", "Noise & Drift", bytes_data, 400.0, 50.0, max_freq_err_hz=1.2, max_duty_err_pct=1.8)
    results.append(res)

    # 7A: Extreme Stress (2 kHz, 5% Duty - Sub-Sample 25 us Pulse)
    t, v = gen.generate_square(0.35, 2000.0, 5.0)
    bytes_data = gen.serialize_to_uart_stream(t, v, 2000.0, 5.0)
    res = harness.evaluate_scenario("SIL-07A", "Extreme Stress (2 kHz, 5% Duty)", "Square (Micro-Pulse 25us)", bytes_data, 2000.0, 5.0, max_freq_err_hz=1005.0, max_duty_err_pct=3.0)
    results.append(res)

    # 7B: High-Speed Carrier (2 kHz, 10% Duty - T_high = 50 us > 40 us Grid)
    t, v = gen.generate_trapezoidal(0.35, 2000.0, 10.0, t_rise_s=5e-6, t_fall_s=5e-6)
    bytes_data = gen.serialize_to_uart_stream(t, v, 2000.0, 10.0)
    res = harness.evaluate_scenario("SIL-07B", "High-Speed (2 kHz, 10% Duty)", "Trapezoidal (T_high=50us)", bytes_data, 2000.0, 10.0, max_freq_err_hz=2.0, max_duty_err_pct=1.0)
    results.append(res)

    # Print Summary Table
    print(f"{'TEST ID':<9} | {'SCENARIO':<32} | {'TARGET':<16} | {'MEASURED':<18} | {'ERROR':<14} | {'VERDICT':<6}")
    print("-" * 105)
    for r in results:
        status = "[PASS]" if r.passed else "[FAIL]"
        target_str = f"{r.target_freq_hz:.1f}Hz, {r.target_duty_pct:.1f}%"
        meas_str = f"{r.mean_freq_hz:.2f}Hz, {r.mean_duty_pct:.2f}%"
        err_str = f"&Delta;f={r.freq_error_hz:.2f} &Delta;D={r.duty_error_pct:.2f}%"
        print(f"{r.test_id:<9} | {r.scenario_name:<32} | {target_str:<16} | {meas_str:<18} | {err_str:<14} | {status}")

    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)
    print("==========================================================================================")
    print(f"   SiL TEST RESULTS: {passed_count} / {total_count} PASSED ({passed_count/total_count*100:.1f}%)")
    print("==========================================================================================")
    return results


if __name__ == "__main__":
    run_all_sil_tests()
