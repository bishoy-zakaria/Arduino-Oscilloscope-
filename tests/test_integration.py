"""
Integration Test: Full pipeline from Physical Layer (Simulator) -> StorageBuffer -> Math Layer.
"""

import time
import unittest
import numpy as np

from adc_oscilloscope.physical_layer.storage_buffer import StorageBuffer
from adc_oscilloscope.physical_layer.serial_receiver import SerialReceiver
from adc_oscilloscope.math_layer.edge_detector import EdgeDetector


class TestPipelineIntegration(unittest.TestCase):
    def test_full_pipeline_simulator_to_edge_detector(self):
        buf = StorageBuffer(capacity=100_000)
        receiver = SerialReceiver(storage_buffer=buf)
        detector = EdgeDetector(v_mid=2.5, hysteresis=0.4)

        # Connect to internal simulator generating 400 Hz PWM @ 50% duty
        connected = receiver.connect("SIMULATOR")
        self.assertTrue(connected)
        self.assertTrue(receiver.is_connected())

        # Wait until sufficient samples are captured (up to 1.0 second timeout)
        t0 = time.time()
        while buf.total_samples < 2000 and (time.time() - t0) < 1.5:
            time.sleep(0.02)

        total_samples = buf.total_samples
        total_packets = buf.total_packets

        receiver.disconnect()
        self.assertFalse(receiver.is_connected())

        # Verify storage buffer received samples
        self.assertGreater(total_samples, 1000)
        self.assertGreater(total_packets, 10)

        # Pull samples from physical buffer into math layer
        ts, volt = buf.get_all()
        cycles = detector.process_samples(ts, volt)

        # In captured samples at 400 Hz, expect at least 20 cycles
        self.assertGreaterEqual(len(cycles), 20)

        # Verify raw frequency and duty cycle
        freqs = [c.frequency_hz for c in cycles]
        duties = [c.duty_cycle_pct for c in cycles]

        # Median / mean should match 400 Hz and 50%
        mean_freq = np.mean(freqs)
        mean_duty = np.mean(duties)

        self.assertAlmostEqual(mean_freq, 400.0, delta=10.0)
        self.assertAlmostEqual(mean_duty, 50.0, delta=4.0)


if __name__ == "__main__":
    unittest.main()
