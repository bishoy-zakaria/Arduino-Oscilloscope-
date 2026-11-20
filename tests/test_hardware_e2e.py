"""
Hardware E2E Test: Tests real Arduino Uno connected to COM14 at 1,000,000 baud.
Validates Physical Layer framing, StorageBuffer throughput, register telemetry,
and Mathematical Layer edge detection on live signals.
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import numpy as np

from adc_oscilloscope.physical_layer.storage_buffer import StorageBuffer
from adc_oscilloscope.physical_layer.serial_receiver import SerialReceiver
from adc_oscilloscope.math_layer.edge_detector import EdgeDetector


def run_hardware_e2e(port: str = "COM14", baudrate: int = 1_000_000, duration_s: float = 2.5):
    print(f"==================================================")
    print(f"       ARDUINO UNO HARDWARE E2E TEST: {port}")
    print(f"==================================================")

    # 1. Initialize Layers
    buffer = StorageBuffer(capacity=500_000)
    errors = []
    conn_logs = []

    def on_conn(connected: bool, msg: str):
        conn_logs.append(f"[{time.strftime('%H:%M:%S')}] Connection: {connected} -> {msg}")
        print(f"  -> {msg}")

    def on_err(err: str):
        errors.append(err)
        print(f"  [ERROR] {err}")

    receiver = SerialReceiver(
        storage_buffer=buffer,
        on_connection_change=on_conn,
        on_error=on_err,
    )
    detector = EdgeDetector(v_mid=2.5, hysteresis=0.4)

    # 2. Connect to COM14
    print(f"\n[Step 1] Connecting to {port} @ {baudrate} baud...")
    success = receiver.connect(port, baudrate)
    if not success:
        print(f"[FAIL] Could not open {port}. Errors: {errors}")
        return False

    # Note: Opening serial port on Arduino Uno resets the ATmega328P via DTR.
    # The bootloader runs for ~1-1.5s before sketch setup() starts streaming.
    print("[Step 2] Listening for incoming DAQ frames (allowing for bootloader startup)...")
    start_time = time.perf_counter()
    first_packet_time = None

    while (time.perf_counter() - start_time) < (duration_s + 2.0):
        if buffer.total_packets > 0 and first_packet_time is None:
            first_packet_time = time.perf_counter()
            print(f"  -> First packet received after {first_packet_time - start_time:.2f}s!")

        # Once streaming, collect for duration_s
        if first_packet_time is not None:
            if (time.perf_counter() - first_packet_time) >= duration_s:
                break
        time.sleep(0.05)

    streaming_duration = (time.perf_counter() - first_packet_time) if first_packet_time else 0.0

    print("\n[Step 3] Disconnecting...")
    receiver.disconnect()

    # 3. Analyze Physical Layer Data
    total_packets = buffer.total_packets
    total_samples = buffer.total_samples
    sync_losses = receiver.parser.sync_losses

    print("\n---------------- Physical Layer Metrics ----------------")
    print(f"  Total Packets Received : {total_packets}")
    print(f"  Total Samples Buffered : {total_samples}")
    print(f"  Sync Losses / Desyncs  : {sync_losses}")
    print(f"  Active Stream Duration : {streaming_duration:.2f} s")

    if total_packets == 0:
        print("\n[FAIL] No packets received from Arduino. Check if sketch is uploaded to COM14.")
        return False

    actual_pkt_rate = total_packets / streaming_duration if streaming_duration > 0 else 0.0
    actual_sample_rate = total_samples / streaming_duration if streaming_duration > 0 else 0.0

    print(f"  Packet Rate            : {actual_pkt_rate:.1f} packets/s (Nominal: 250.0)")
    print(f"  Sample Throughput      : {actual_sample_rate:.1f} samples/s (Nominal: 25,000)")

    # Telemetry registers verification
    f_cpu = buffer.latest_f_cpu
    pwm_icr1 = buffer.latest_pwm_icr1
    pwm_ocr1a = buffer.latest_pwm_ocr1a
    pwm_psc = buffer.latest_pwm_prescaler
    adc_ocr2a = buffer.latest_adc_ocr2a
    adc_psc = buffer.latest_adc_prescaler

    print("\n---------------- Hardware Register Telemetry ------------")
    print(f"  F_CPU                  : {f_cpu} Hz ({f_cpu/1e6:.1f} MHz)")
    print(f"  Timer2 OCR2A (ADC)     : {adc_ocr2a} (Expected: 79)")
    print(f"  Timer2 Prescaler       : {adc_psc} (Expected: 8)")
    print(f"  Timer1 ICR1 (PWM TOP)  : {pwm_icr1}")
    print(f"  Timer1 OCR1A (Duty)    : {pwm_ocr1a}")
    print(f"  Timer1 Prescaler       : {pwm_psc}")

    if pwm_psc > 0 and (pwm_icr1 + 1) > 0:
        hw_pwm_freq = float(f_cpu) / (float(pwm_psc) * float(pwm_icr1 + 1))
        hw_pwm_duty = (float(pwm_ocr1a) / float(pwm_icr1 + 1)) * 100.0
        print(f"  Computed HW PWM Target : {hw_pwm_freq:.2f} Hz @ {hw_pwm_duty:.1f}% duty")

    # 4. Analyze Signal Voltage Data
    ts_all, volt_all = buffer.get_all()
    v_min = float(np.min(volt_all))
    v_max = float(np.max(volt_all))
    v_mean = float(np.mean(volt_all))
    v_pp = v_max - v_min

    print("\n---------------- Voltage Signal Analysis ----------------")
    print(f"  V_min                  : {v_min:.3f} V")
    print(f"  V_max                  : {v_max:.3f} V")
    print(f"  V_mean                 : {v_mean:.3f} V")
    print(f"  V_peak-to-peak (Vpp)   : {v_pp:.3f} V")

    # 5. Analyze Mathematical Layer (Edge Detection)
    print("\n---------------- Mathematical Layer Analysis ------------")
    if v_pp > 0.4:
        v_mid, hyst = detector.auto_adjust_thresholds(volt_all)
        print(f"  Auto-tuned Thresholds  : V_mid = {v_mid:.2f} V, Hysteresis = ±{hyst:.2f} V")
    else:
        print(f"  Low amplitude signal detected (Vpp = {v_pp:.2f}V). Pin A0 may be floating or grounded.")
        print(f"  Tip: Connect Arduino Pin 9 (PWM output) to Pin A0 (ADC input) to test loopback!")
        detector.set_thresholds(v_mid=2.5, hysteresis=0.4)

    cycles = detector.process_samples(ts_all, volt_all)
    print(f"  Total Valid Cycles     : {len(cycles)}")

    if len(cycles) > 0:
        freqs = [c.frequency_hz for c in cycles]
        duties = [c.duty_cycle_pct for c in cycles]

        print(f"  Cycle Frequency (Mean) : {np.mean(freqs):.2f} Hz")
        print(f"  Cycle Frequency (Std)  : {np.std(freqs):.2f} Hz")
        print(f"  Cycle Frequency (Min/Max): {np.min(freqs):.2f} / {np.max(freqs):.2f} Hz")
        print(f"  Cycle Duty Cycle (Mean): {np.mean(duties):.2f} %")
        print(f"  Cycle Duty Cycle (Std) : {np.std(duties):.2f} %")
    else:
        print("  Note: No rising->falling->rising edge transitions detected.")
        if v_pp < 0.5:
            print("  (A0 voltage is constant. If you want to measure the Arduino's own PWM, connect a jumper wire from Pin 9 to Pin A0.)")

    # 6. Verification Assertions
    assert total_packets >= 50, f"Expected at least 50 packets, got {total_packets}"
    assert f_cpu == 16_000_000, f"Expected 16MHz clock, got {f_cpu}"
    assert adc_ocr2a == 79, f"Expected Timer2 OCR2A = 79, got {adc_ocr2a}"
    assert adc_psc == 8, f"Expected Timer2 Prescaler = 8, got {adc_psc}"
    assert actual_sample_rate >= 20000, f"Expected at least 20 kSPS throughput, got {actual_sample_rate}"

    print(f"\n==================================================")
    print(f"   >>> ALL HARDWARE E2E CHECKS PASSED ON COM14! <<<")
    print(f"==================================================")
    return True


if __name__ == "__main__":
    port_name = sys.argv[1] if len(sys.argv) > 1 else "COM14"
    ok = run_hardware_e2e(port=port_name)
    sys.exit(0 if ok else 1)
