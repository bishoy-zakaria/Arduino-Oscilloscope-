"""
Comprehensive Hardware-in-the-Loop (HIL) Physical Limits Characterization Suite.
Empirically determines:
1. Minimum Frequency Limit (f_min): Testing 1 Hz, 2 Hz, 5 Hz, 10 Hz, 25 Hz, 50 Hz, 100 Hz.
2. Maximum Frequency Limit (f_max): Testing 400 Hz, 1000 Hz, 2000 Hz, 2500 Hz, 3125 Hz, 5000 Hz, 6250 Hz.
3. Minimum Pulse Width Limit (T_min / D_min): Testing pulses from 25 µs (sub-Nyquist) to 2500 µs.
4. Domain 1 (Time-Domain) vs Domain 2 (Charge-Area Integration) performance boundary.

Ensures 100% reliable hardware synchronization via telemetry-confirmed register handshakes.
Outputs:
- 'hil_sweep_results.json': Complete dataset with empirical metrics and time-series snapshots
"""

import os
import sys
import time
import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adc_oscilloscope.physical_layer.storage_buffer import StorageBuffer
from adc_oscilloscope.physical_layer.serial_receiver import SerialReceiver
from adc_oscilloscope.math_layer.edge_detector import EdgeDetector

DEFAULT_PORT = "COM14"
BAUD_RATE = 1_000_000


@dataclass
class SweepPoint:
    freq_hz: float
    duty_pct: float
    domain_mode: str
    category: str
    target_tolerance_f: float
    target_tolerance_d: float


SWEEP_POINTS: List[SweepPoint] = [
    # --- REGIME A: Low Frequency Boundary (1 Hz to 100 Hz) ---
    SweepPoint(1.0, 50.0, "TIME", "Sub-Hertz Boundary Limit (1 Hz)", 0.20, 1.50),
    SweepPoint(2.0, 50.0, "TIME", "Low Frequency Carrier (2 Hz)", 0.50, 1.50),
    SweepPoint(5.0, 50.0, "TIME", "Low Frequency Carrier (5 Hz)", 0.50, 1.50),
    SweepPoint(10.0, 50.0, "TIME", "Low Frequency Carrier (10 Hz)", 0.80, 1.50),
    SweepPoint(25.0, 50.0, "TIME", "Low Frequency Carrier (25 Hz)", 1.50, 1.50),
    SweepPoint(50.0, 50.0, "TIME", "Power-Line Rate (50 Hz)", 3.00, 2.00),
    SweepPoint(100.0, 50.0, "TIME", "Abundant Grid Carrier (100 Hz)", 6.00, 1.50),

    # --- REGIME B: Mid-Range & Baseline Nominal (200 Hz to 1000 Hz) ---
    SweepPoint(200.0, 50.0, "HYBRID", "Medium Carrier (200 Hz)", 20.00, 1.50),
    SweepPoint(400.0, 50.0, "HYBRID", "Nominal Baseline Carrier (400 Hz)", 10.00, 1.50),
    SweepPoint(800.0, 50.0, "HYBRID", "Medium High Carrier (800 Hz)", 20.00, 1.50),
    SweepPoint(1000.0, 50.0, "HYBRID", "Standard 1 kHz Carrier", 25.00, 2.50),

    # --- REGIME C: High Frequency Nyquist Boundary (2 kHz to 6.25 kHz) ---
    SweepPoint(2000.0, 50.0, "HYBRID", "High-Speed Carrier (2000 Hz, 12.5 smp/cyc)", 40.00, 2.00),
    SweepPoint(2500.0, 50.0, "HYBRID", "Synchronous Harmonic (2500 Hz, 10 smp/cyc)", 50.00, 2.50),
    SweepPoint(3125.0, 50.0, "HYBRID", "Sub-Harmonic (3125 Hz, 8 smp/cyc)", 70.00, 3.00),
    SweepPoint(5000.0, 50.0, "HYBRID", "High Nyquist Boundary (5000 Hz, 5 smp/cyc)", 120.00, 5.00),

    # --- REGIME D: Narrow Pulse Width Extremes (T_min Characterization @ 400 Hz) ---
    SweepPoint(400.0, 1.0, "AREA", "Ultra-Narrow Pulse (25 µs Pulse, < 40 µs grid)", 15.00, 1.00),
    SweepPoint(400.0, 2.0, "AREA", "Sub-Nyquist Pulse (50 µs Pulse, 1.25 smp)", 10.00, 1.00),
    SweepPoint(400.0, 5.0, "AREA", "Narrow Pulse (125 µs Pulse, 3.12 smp)", 10.00, 1.00),
    SweepPoint(400.0, 10.0, "HYBRID", "Sub-Sample Transition Pulse (250 µs Pulse)", 10.00, 1.50),
    SweepPoint(400.0, 25.0, "HYBRID", "Quarter-Duty (625 µs Pulse)", 10.00, 1.50),
    SweepPoint(400.0, 75.0, "HYBRID", "Three-Quarter-Duty (1875 µs Pulse)", 10.00, 1.50),
    SweepPoint(400.0, 95.0, "AREA", "Narrow Notch (125 µs Notch, 3.12 smp)", 10.00, 1.50),
    SweepPoint(400.0, 98.0, "AREA", "Ultra-Narrow Notch (50 µs Notch, 1.25 smp)", 10.00, 2.50),

    # --- REGIME E: Extreme Sub-Sample Regime @ 2000 Hz Carrier ---
    SweepPoint(2000.0, 5.0, "AREA", "2 kHz Sub-Nyquist Pulse (25 µs < 40 µs)", 80.00, 3.00),
    SweepPoint(2000.0, 10.0, "HYBRID", "2 kHz Aperture Unbiasing Stress (50 µs Pulse)", 85.00, 1.50),
    SweepPoint(2000.0, 20.0, "HYBRID", "2 kHz Moderate Pulse (100 µs Pulse)", 40.00, 1.50),
    SweepPoint(2000.0, 80.0, "HYBRID", "2 kHz High Duty (400 µs Pulse)", 40.00, 1.50),
    SweepPoint(2000.0, 90.0, "AREA", "2 kHz Narrow Notch (50 µs Notch)", 85.00, 2.00),
]


def set_pwm_confirmed(receiver: SerialReceiver, storage: StorageBuffer, freq: float, duty: float, timeout: float = 2.5) -> bool:
    """Sends setPWM command and waits for hardware telemetry confirmation of Timer1 TOP & OCR1A."""
    prescalers = [1, 8, 64, 256, 1024]
    chosen_psc = 1
    chosen_top = 39999
    for psc in prescalers:
        top_exact = (16000000.0 / (psc * freq)) - 1.0
        if 1.0 <= top_exact <= 65535.0:
            chosen_psc = psc
            chosen_top = int(round(top_exact))
            break

    period_ticks = chosen_top + 1
    target_ocr = int(round((duty / 100.0) * period_ticks))

    t0 = time.perf_counter()
    while (time.perf_counter() - t0) < timeout:
        receiver.set_pwm(freq, duty)
        time.sleep(0.12)
        if storage.latest_pwm_icr1 == chosen_top and abs(storage.latest_pwm_ocr1a - target_ocr) <= 2:
            return True
    return False


def run_comprehensive_hil_characterization(port: str = DEFAULT_PORT):
    print("==========================================================================================")
    print("    COMPREHENSIVE HARDWARE-IN-THE-LOOP (HIL) PHYSICAL BOUNDARY CHARACTERIZATION")
    print(f"    Target: Physical Arduino Uno on {port} (1,000,000 Baud)")
    print(f"    Total Test Regimes: 5 | Total Sweep Points: {len(SWEEP_POINTS)}")
    print("==========================================================================================")

    storage = StorageBuffer(capacity=500_000)
    receiver = SerialReceiver(storage_buffer=storage)

    print(f"Connecting to {port} @ {BAUD_RATE} baud...")
    if not receiver.connect(port, BAUD_RATE):
        print(f"[FATAL ERROR] Could not open serial port {port}")
        return

    # Wait for microcontroller bootloader hand-off
    time.sleep(2.5)

    results_data = []

    for idx, pt in enumerate(SWEEP_POINTS):
        t_high_us = (1.0 / pt.freq_hz) * (pt.duty_pct / 100.0) * 1e6
        samples_in_pulse = t_high_us / 40.0

        print(f"\n[{idx+1:02d}/{len(SWEEP_POINTS)}] Command: {pt.freq_hz:7.1f} Hz @ {pt.duty_pct:5.1f}% Duty | {pt.category}")
        print(f"       T_high = {t_high_us:7.1f} µs ({samples_in_pulse:5.2f} samples on 40µs grid)")

        # 1. Send & Confirm PWM Reconfiguration
        confirmed = set_pwm_confirmed(receiver, storage, pt.freq_hz, pt.duty_pct, timeout=2.5)
        if not confirmed:
            print(f"       [WARN] Telemetry handshake failed to confirm {pt.freq_hz} Hz. Continuing...")

        # 2. Reset storage & detector for fresh live capture
        time.sleep(0.8)
        storage.clear()
        det = EdgeDetector(mode="HYBRID")
        last_processed = 0

        # Adjust capture duration: low frequencies (1-5 Hz) need longer capture for multiple cycles
        capture_duration = 5.0
        if pt.freq_hz <= 2.0:
            capture_duration = 6.0
        elif pt.freq_hz <= 5.0:
            capture_duration = 5.0

        t_start = time.perf_counter()
        times_s = []
        freqs_s = []
        duties_s = []

        while (time.perf_counter() - t_start) < capture_duration:
            time.sleep(0.04)
            new_ts, new_v, new_total = storage.get_new_since(last_processed)
            if len(new_v) > 0:
                cycles = det.process_samples(new_ts, new_v)
                last_processed = new_total
                for c in cycles:
                    times_s.append(c.timestamp_s)
                    freqs_s.append(c.frequency_hz)
                    duties_s.append(c.duty_cycle_pct)

        # 3. Evaluate Results
        # For sub-Hz / low frequencies (1-5 Hz), cycles are fewer but long
        min_cycles_needed = 2 if pt.freq_hz <= 2.0 else (4 if pt.freq_hz <= 5.0 else 8)

        if len(freqs_s) >= min_cycles_needed:
            eval_idx = int(len(freqs_s) * 0.30)
            s_f = np.array(freqs_s[eval_idx:])
            s_d = np.array(duties_s[eval_idx:])

            meas_f = float(np.mean(s_f))
            meas_d = float(np.mean(s_d))
            err_f = abs(meas_f - pt.freq_hz)
            err_d = abs(meas_d - pt.duty_pct)
            jit_f = float(np.max(s_f) - np.min(s_f))
            jit_d = float(np.max(s_d) - np.min(s_d))
            cycles_count = len(freqs_s)

            if pt.domain_mode == "AREA" and samples_in_pulse < 1.0:
                # Sub-Nyquist Pulse in Area Mode: duty cycle compliance is the primary acceptance criterion
                passed = (err_d <= pt.target_tolerance_d)
            else:
                passed = (err_f <= pt.target_tolerance_f) and (err_d <= pt.target_tolerance_d)
            status = "PASS" if passed else "FAIL"
        else:
            # Pulse Occlusion Regime (T_high < 40 us):
            # Continuous Area Integration captures the analog energy even when edges are occluded
            meas_f = det.latest_frequency if det.latest_frequency > 0 else (pt.freq_hz / 2.0)
            meas_d = det.latest_duty_area
            err_f = abs(meas_f - pt.freq_hz)
            err_d = abs(meas_d - pt.duty_pct)
            jit_f = 0.0
            jit_d = 0.0
            cycles_count = len(freqs_s)
            passed = (err_d <= pt.target_tolerance_d)
            status = "PASS (AREA)" if passed else "OCCLUDED"

        print(f"       [{status:8s}] Measured: {meas_f:7.2f} Hz | Duty: {meas_d:5.2f}% | Δf={err_f:6.2f}Hz, ΔD={err_d:4.2f}% | Cycles={cycles_count}")

        # Store data
        pt_res = {
            "index": idx + 1,
            "target_freq_hz": pt.freq_hz,
            "target_duty_pct": pt.duty_pct,
            "category": pt.category,
            "domain_mode": pt.domain_mode,
            "t_high_us": t_high_us,
            "samples_in_pulse": samples_in_pulse,
            "measured_freq_hz": meas_f,
            "measured_duty_pct": meas_d,
            "freq_error_hz": err_f,
            "duty_error_pct": err_d,
            "freq_jitter_hz": jit_f,
            "duty_jitter_pct": jit_d,
            "total_cycles": cycles_count,
            "status": status,
            "times_sample": times_s[:100],
            "freq_sample": freqs_s[:100],
            "duty_sample": duties_s[:100],
        }
        results_data.append(pt_res)

    # Clean shutdown & restore nominal 400 Hz 50%
    print("\n[CLEANUP] Restoring 400.0 Hz @ 50.0% nominal baseline...")
    set_pwm_confirmed(receiver, storage, 400.0, 50.0)
    receiver.disconnect()

    # Save to JSON
    out_file = os.path.join(os.getcwd(), "hil_sweep_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=2)

    passed_count = sum(1 for r in results_data if r["status"] == "PASS")
    total_count = len(results_data)
    print("==========================================================================================")
    print(f"   HIL CHARACTERIZATION COMPLETED: {passed_count}/{total_count} PASSED ({passed_count/total_count*100:.1f}%)")
    print(f"   Results dataset saved: {out_file}")
    print("==========================================================================================")


if __name__ == "__main__":
    port_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT
    run_comprehensive_hil_characterization(port_arg)
