"""
Software-in-the-Loop (SiL) Test Suite: Executes end-to-end simulated UART scenarios
against IEEE 181-2011, IEEE 1057, and ISO 16750-2 standards.
"""

import unittest
import numpy as np

from tests.sil.waveform_generator import SilWaveformGenerator
from tests.sil.sil_harness import SilHarness


class TestSilScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gen = SilWaveformGenerator(fs=25000.0, vref=5.0)
        cls.harness = SilHarness()

    # =========================================================================
    # SCENARIO 1: Standard Waveforms per IEEE 181-2011
    # =========================================================================
    def test_scenario_1a_square_wave_nominal(self):
        """Scenario 1A: Nominal Square Wave @ 400 Hz, 50% Duty."""
        t, v = self.gen.generate_square(duration_s=0.25, freq_hz=400.0, duty_pct=50.0)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=400.0, duty_pct=50.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC1-A",
            scenario_name="Nominal Square Wave (400 Hz, 50%)",
            waveform_type="Square (Ideal IEEE 181)",
            uart_bytes=uart_bytes,
            target_freq_hz=400.0,
            target_duty_pct=50.0,
            mode="HYBRID",
            max_freq_err_hz=0.5,
            max_duty_err_pct=0.7,
        )
        self.assertTrue(res.passed, res.notes)
        self.assertLess(res.freq_jitter_pk_pk_hz, 1.2)

    def test_scenario_1b_trapezoidal_linear_slew(self):
        """Scenario 1B: Trapezoidal Wave with Finite Rise/Fall (25 us) per IEEE 181."""
        t, v = self.gen.generate_trapezoidal(
            duration_s=0.25, freq_hz=400.0, duty_pct=50.0, t_rise_s=25e-6, t_fall_s=25e-6
        )
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=400.0, duty_pct=50.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC1-B",
            scenario_name="Trapezoidal Wave (25 us Rise/Fall Ramps)",
            waveform_type="Trapezoidal (IEEE 181)",
            uart_bytes=uart_bytes,
            target_freq_hz=400.0,
            target_duty_pct=50.0,
            mode="HYBRID",
            max_freq_err_hz=0.6,
            max_duty_err_pct=0.6,
        )
        self.assertTrue(res.passed, res.notes)

    def test_scenario_1c_sinusoidal_wave(self):
        """Scenario 1C: Sinusoidal Zero-Crossing Waveform @ 400 Hz."""
        t, v = self.gen.generate_sine(duration_s=0.25, freq_hz=400.0, v_offset=2.5, v_amplitude=2.3)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=400.0, duty_pct=50.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC1-C",
            scenario_name="Sinusoidal Waveform (400 Hz)",
            waveform_type="Sine Wave (Continuous)",
            uart_bytes=uart_bytes,
            target_freq_hz=400.0,
            target_duty_pct=50.0,
            mode="HYBRID",
            max_freq_err_hz=0.8,
            max_duty_err_pct=1.0,
        )
        self.assertTrue(res.passed, res.notes)

    def test_scenario_1d_triangular_wave(self):
        """Scenario 1D: Triangular Wave @ 200 Hz (Linear Ramp Zero-Crossing)."""
        t, v = self.gen.generate_triangular(duration_s=0.25, freq_hz=200.0)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=200.0, duty_pct=50.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC1-D",
            scenario_name="Triangular Waveform (200 Hz)",
            waveform_type="Triangular (Linear)",
            uart_bytes=uart_bytes,
            target_freq_hz=200.0,
            target_duty_pct=50.0,
            mode="HYBRID",
            max_freq_err_hz=0.8,
            max_duty_err_pct=1.0,
        )
        self.assertTrue(res.passed, res.notes)

    # =========================================================================
    # SCENARIO 2: Extreme Duty Cycles & Continuous Charge-Area Integration
    # =========================================================================
    def test_scenario_2a_ultra_low_duty_cycle(self):
        """Scenario 2A: Ultra-Low Duty Cycle (2.0% @ 400 Hz, Pulse Width = 50 us)."""
        t, v = self.gen.generate_square(duration_s=0.30, freq_hz=400.0, duty_pct=2.0)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=400.0, duty_pct=2.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC2-A",
            scenario_name="Ultra-Low Duty Cycle (2.0%)",
            waveform_type="Square (Narrow High Pulse)",
            uart_bytes=uart_bytes,
            target_freq_hz=400.0,
            target_duty_pct=2.0,
            mode="HYBRID",
            max_freq_err_hz=1.0,
            max_duty_err_pct=0.8,
        )
        self.assertTrue(res.passed, res.notes)

    def test_scenario_2b_ultra_high_duty_cycle(self):
        """Scenario 2B: Ultra-High Duty Cycle (95.0% @ 400 Hz, Low Notch = 125 us)."""
        t, v = self.gen.generate_square(duration_s=0.30, freq_hz=400.0, duty_pct=95.0)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=400.0, duty_pct=95.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC2-B",
            scenario_name="Ultra-High Duty Cycle (95.0%)",
            waveform_type="Square (Narrow Low Notch)",
            uart_bytes=uart_bytes,
            target_freq_hz=400.0,
            target_duty_pct=95.0,
            mode="HYBRID",
            max_freq_err_hz=1.0,
            max_duty_err_pct=0.8,
        )
        self.assertTrue(res.passed, res.notes)

    # =========================================================================
    # SCENARIO 3: Carrier Frequency Dynamic Range
    # =========================================================================
    def test_scenario_3a_low_frequency(self):
        """Scenario 3A: Low Frequency (10 Hz, 2500 samples/cycle)."""
        t, v = self.gen.generate_square(duration_s=0.80, freq_hz=10.0, duty_pct=40.0)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=10.0, duty_pct=40.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC3-A",
            scenario_name="Low Frequency (10 Hz)",
            waveform_type="Square (Abundant Samples)",
            uart_bytes=uart_bytes,
            target_freq_hz=10.0,
            target_duty_pct=40.0,
            mode="HYBRID",
            max_freq_err_hz=0.2,
            max_duty_err_pct=0.5,
        )
        self.assertTrue(res.passed, res.notes)

    def test_scenario_3b_high_frequency_sparse(self):
        """Scenario 3B: High Frequency (1000 Hz, 25 samples/cycle)."""
        t, v = self.gen.generate_square(duration_s=0.25, freq_hz=1000.0, duty_pct=50.0)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=1000.0, duty_pct=50.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC3-B",
            scenario_name="High Frequency (1000 Hz)",
            waveform_type="Square (Sparse Sampling)",
            uart_bytes=uart_bytes,
            target_freq_hz=1000.0,
            target_duty_pct=50.0,
            mode="HYBRID",
            max_freq_err_hz=2.0,
            max_duty_err_pct=2.0,
        )
        self.assertTrue(res.passed, res.notes)

    # =========================================================================
    # SCENARIO 4: Pure DC States & Boundary Transitions
    # =========================================================================
    def test_scenario_4a_pure_dc_high(self):
        """Scenario 4A: Pure DC High (5.0V, 0 Hz, 100% Duty, Zero False Triggers)."""
        t, v = self.gen.generate_pure_dc(duration_s=0.30, v_level=4.95)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=0.0, duty_pct=100.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC4-A",
            scenario_name="Pure DC High Hold (5.0 V)",
            waveform_type="DC Plateau (Flat High)",
            uart_bytes=uart_bytes,
            target_freq_hz=0.0,
            target_duty_pct=100.0,
            mode="HYBRID",
            expect_dc=True,
        )
        self.assertTrue(res.passed, res.notes)

    def test_scenario_4b_pure_dc_low(self):
        """Scenario 4B: Pure DC Low (0.0V, 0 Hz, 0% Duty, Zero False Triggers)."""
        t, v = self.gen.generate_pure_dc(duration_s=0.30, v_level=0.05)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=0.0, duty_pct=0.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC4-B",
            scenario_name="Pure DC Low Hold (0.0 V)",
            waveform_type="DC Baseline (Flat Low)",
            uart_bytes=uart_bytes,
            target_freq_hz=0.0,
            target_duty_pct=0.0,
            mode="HYBRID",
            expect_dc=True,
        )
        self.assertTrue(res.passed, res.notes)

    def test_scenario_4c_dc_to_pwm_cold_start(self):
        """Scenario 4C: Cold-Start Transition (Pure DC Low -> PWM 400 Hz)."""
        t, v = self.gen.generate_dc_to_pwm(
            dc_duration_s=0.15, pwm_duration_s=0.25, freq_hz=400.0, duty_pct=50.0
        )
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=400.0, duty_pct=50.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC4-C",
            scenario_name="Cold-Start Transition (DC -> PWM)",
            waveform_type="Dynamic Boundary Transition",
            uart_bytes=uart_bytes,
            target_freq_hz=400.0,
            target_duty_pct=50.0,
            mode="HYBRID",
            max_freq_err_hz=1.0,
            max_duty_err_pct=1.0,
            steady_tail_count=15,
        )
        self.assertTrue(res.passed, res.notes)

    # =========================================================================
    # SCENARIO 5: Dynamic Step Tracking per IEEE 1057
    # =========================================================================
    def test_scenario_5a_duty_step_fast_attack(self):
        """Scenario 5A: Instantaneous Duty Cycle Step (20% -> 80%)."""
        t, v = self.gen.generate_duty_step(
            duration1_s=0.20, duration2_s=0.25, freq_hz=400.0, duty1_pct=20.0, duty2_pct=80.0
        )
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=400.0, duty_pct=80.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC5-A",
            scenario_name="Instantaneous Duty Step (20% -> 80%)",
            waveform_type="Step Function (Fast Attack)",
            uart_bytes=uart_bytes,
            target_freq_hz=400.0,
            target_duty_pct=80.0,
            mode="HYBRID",
            max_freq_err_hz=1.0,
            max_duty_err_pct=1.8,
            steady_tail_count=15,
        )
        self.assertTrue(res.passed, res.notes)

    # =========================================================================
    # SCENARIO 6: Environmental Disturbances per ISO 16750-2
    # =========================================================================
    def test_scenario_6a_noise_and_mains_hum(self):
        """Scenario 6A: Additive Gaussian Noise (50 mV RMS) and 50 Hz Hum (100 mV)."""
        t, v = self.gen.generate_square(duration_s=0.30, freq_hz=400.0, duty_pct=50.0)
        v_disturbed = self.gen.add_disturbances(
            v, t, noise_rms_v=0.04, mains_hum_amp_v=0.08, dc_drift_v=0.15
        )
        uart_bytes = self.gen.serialize_to_uart_stream(t, v_disturbed, freq_hz=400.0, duty_pct=50.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC6-A",
            scenario_name="ISO 16750-2 Noise, Hum & Drift Disturbance",
            waveform_type="Square with Noise & Drift",
            uart_bytes=uart_bytes,
            target_freq_hz=400.0,
            target_duty_pct=50.0,
            mode="HYBRID",
            max_freq_err_hz=1.2,
            max_duty_err_pct=1.8,
        )
        self.assertTrue(res.passed, res.notes)

    # =========================================================================
    # SCENARIO 7: Extreme Stress Test (2 kHz, 5% Duty - Sub-Sample Micro-Pulse)
    # =========================================================================
    def test_scenario_7a_extreme_stress_2khz_5pct(self):
        """Scenario 7A: Extreme Stress (2000 Hz, 5% Duty, Pulse = 25 us < 40 us Sample Grid)."""
        t, v = self.gen.generate_square(duration_s=0.35, freq_hz=2000.0, duty_pct=5.0)
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=2000.0, duty_pct=5.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC7-A",
            scenario_name="Extreme Stress (2000 Hz, 5% Duty)",
            waveform_type="Square (Micro-Pulse 25us)",
            uart_bytes=uart_bytes,
            target_freq_hz=2000.0,
            target_duty_pct=5.0,
            mode="HYBRID",
            max_freq_err_hz=1005.0,
            max_duty_err_pct=3.0,
        )
        self.assertTrue(res.passed, res.notes)

    def test_scenario_7b_stress_2khz_10pct(self):
        """Scenario 7B: 2000 Hz, 10% Duty (Pulse = 50 us > 40 us Sample Grid -> 0% Pulse Skip)."""
        t, v = self.gen.generate_trapezoidal(
            duration_s=0.35, freq_hz=2000.0, duty_pct=10.0, t_rise_s=5e-6, t_fall_s=5e-6
        )
        uart_bytes = self.gen.serialize_to_uart_stream(t, v, freq_hz=2000.0, duty_pct=10.0)

        res = self.harness.evaluate_scenario(
            test_id="SIL-SC7-B",
            scenario_name="Stress Test (2000 Hz, 10% Duty)",
            waveform_type="Trapezoidal (T_high = 50 us > 40 us Grid)",
            uart_bytes=uart_bytes,
            target_freq_hz=2000.0,
            target_duty_pct=10.0,
            mode="HYBRID",
            max_freq_err_hz=2.0,
            max_duty_err_pct=1.0,
        )
        self.assertTrue(res.passed, res.notes)


if __name__ == "__main__":
    unittest.main()
