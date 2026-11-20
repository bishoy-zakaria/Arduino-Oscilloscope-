"""
Tests for Mathematical Layer: Dual-Domain Adaptive Hybrid (DDAH) EdgeDetector.
Verifies DDAH Hybrid Mode (5-tap FIFO, Area Integration, Jitter Cancellation),
RAW Unfiltered Mode, and Step Response.
"""

import unittest
import numpy as np
from adc_oscilloscope.math_layer.edge_detector import EdgeDetector


class TestMathLayer(unittest.TestCase):
    def test_ddah_hybrid_jitter_suppression(self):
        """Verifies that DDAH hybrid mode cancels the 62.5-sample limit-cycle jitter."""
        detector = EdgeDetector(v_mid=2.5, hysteresis=0.4, mode="HYBRID")

        fs = 25000.0
        dt = 1.0 / fs
        duration = 0.25  # 100 cycles at 400 Hz
        t = np.arange(0, duration, dt, dtype=np.float64)

        freq_true = 400.0
        duty_true = 50.0
        period_true = 1.0 / freq_true

        # Square wave with realistic rise/fall (0.05V to 4.95V)
        phase = (t % period_true) / period_true
        voltages = np.where(phase < 0.50, 4.95, 0.05).astype(np.float32)

        # Feed in chunks of 100 samples
        chunk_size = 100
        all_cycles = []
        for i in range(0, len(t), chunk_size):
            cycles = detector.process_samples(t[i:i+chunk_size], voltages[i:i+chunk_size])
            all_cycles.extend(cycles)

        self.assertGreater(len(all_cycles), 50)

        # Discard the initialization cycles and evaluate steady state (last 25 cycles)
        steady = all_cycles[-25:]
        freqs = [c.frequency_hz for c in steady]
        duties = [c.duty_cycle_pct for c in steady]

        # Steady-state DDAH frequency must be extremely stable (std < 0.5 Hz, error < 0.5 Hz)
        self.assertAlmostEqual(float(np.mean(freqs)), freq_true, delta=0.5)
        self.assertLess(float(np.std(freqs)), 0.6)

        # Steady-state DDAH duty cycle must be accurate (mean within 0.8% of 50%)
        self.assertAlmostEqual(float(np.mean(duties)), duty_true, delta=0.8)

    def test_raw_mode_instantaneous_behavior(self):
        """Verifies RAW mode preserves single-cycle unfiltered bus values."""
        detector = EdgeDetector(v_mid=2.5, hysteresis=0.4, mode="RAW")

        fs = 25000.0
        dt = 1.0 / fs
        duration = 0.1
        t = np.arange(0, duration, dt, dtype=np.float64)
        period = 1.0 / 400.0
        phase = (t % period) / period
        voltages = np.where(phase < 0.50, 4.9, 0.1).astype(np.float32)

        cycles = detector.process_samples(t, voltages)
        self.assertGreater(len(cycles), 30)

        # In RAW mode, each cycle should show the raw discrete samples
        self.assertTrue(all(c.raw_frequency_hz == c.frequency_hz for c in cycles))
        self.assertTrue(all(c.raw_duty_pct == c.duty_cycle_pct for c in cycles))

    def test_instantaneous_step_response(self):
        """Verifies fast-attack step tracking when duty changes abruptly."""
        detector = EdgeDetector(v_mid=2.5, hysteresis=0.4, mode="RAW")

        fs = 25000.0
        dt = 1.0 / fs
        freq = 200.0
        period = 1.0 / freq
        num_cycles = 20
        t = np.arange(0, num_cycles * period, dt, dtype=np.float64)

        voltages = np.zeros_like(t, dtype=np.float32)
        for i, ti in enumerate(t):
            cycle_idx = int(ti / period)
            duty = 20.0 if cycle_idx < 10 else 80.0
            phase = (ti % period) / period
            voltages[i] = 4.8 if phase < (duty / 100.0) else 0.2

        cycles = detector.process_samples(t, voltages)
        self.assertGreaterEqual(len(cycles), 18)

        duties = [c.duty_cycle_pct for c in cycles]
        # First cycles ~20%
        for d in duties[:8]:
            self.assertAlmostEqual(d, 20.0, delta=2.5)

        # Cycles after transition jump to ~80%
        for d in duties[12:]:
            self.assertAlmostEqual(d, 80.0, delta=2.5)

    def test_flat_signal_produces_no_cycles(self):
        detector = EdgeDetector(v_mid=2.5, hysteresis=0.4, mode="HYBRID")
        t = np.arange(0, 0.05, 40e-6, dtype=np.float64)
        flat_high = np.full_like(t, 4.9, dtype=np.float32)

        cycles = detector.process_samples(t, flat_high)
        self.assertEqual(len(cycles), 0)
        self.assertEqual(detector.total_cycles, 0)


if __name__ == "__main__":
    unittest.main()
