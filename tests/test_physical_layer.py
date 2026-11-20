"""
Tests for Physical Layer components: PacketParser, StorageBuffer, Simulator.
"""

import unittest
import numpy as np
from adc_oscilloscope.physical_layer.packet_parser import (
    StreamParser,
    pack_adc_packet,
    SYNC_HEADER,
    SAMPLES_PER_PACKET,
    TOTAL_FRAME_SIZE,
)
from adc_oscilloscope.physical_layer.storage_buffer import StorageBuffer
from adc_oscilloscope.physical_layer.simulator import ArduinoSimulator


class TestPhysicalLayer(unittest.TestCase):
    def test_packet_pack_and_parse(self):
        parser = StreamParser(vref=5.0, adc_max_count=1023.0)

        # 100 samples alternating 0 and 1023
        samples = [1023 if i % 2 == 0 else 0 for i in range(SAMPLES_PER_PACKET)]
        packet_bytes = pack_adc_packet(
            timestamp_us=4000,
            f_cpu_hz=16_000_000,
            pwm_icr1=4999,
            pwm_ocr1a=2500,
            pwm_prescaler=8,
            adc_ocr2a=79,
            adc_prescaler=8,
            samples=samples,
        )

        self.assertEqual(len(packet_bytes), TOTAL_FRAME_SIZE)

        frames = list(parser.parse_stream(packet_bytes))
        self.assertEqual(len(frames), 1)
        f = frames[0]

        self.assertEqual(f.timestamp_us, 4000)
        self.assertEqual(f.f_cpu_hz, 16_000_000)
        self.assertEqual(f.pwm_icr1, 4999)
        self.assertEqual(f.pwm_ocr1a, 2500)
        self.assertEqual(f.pwm_prescaler, 8)
        self.assertEqual(f.adc_ocr2a, 79)
        self.assertEqual(f.adc_prescaler, 8)
        self.assertEqual(len(f.raw_samples), 100)
        self.assertEqual(len(f.voltages), 100)
        self.assertEqual(len(f.timestamps_s), 100)

        # Voltages should be 5.0 and 0.0
        self.assertTrue(np.isclose(f.voltages[0], 5.0, atol=0.01))
        self.assertTrue(np.isclose(f.voltages[1], 0.0, atol=0.01))

        # Timestamps should have 40 us spacing
        dt = f.timestamps_s[1] - f.timestamps_s[0]
        self.assertTrue(np.isclose(dt, 40.0e-6, atol=1e-9))

    def test_parser_resync_after_garbage(self):
        parser = StreamParser()

        samples = [512] * SAMPLES_PER_PACKET
        valid_packet = pack_adc_packet(
            timestamp_us=10000,
            f_cpu_hz=16_000_000,
            pwm_icr1=1000,
            pwm_ocr1a=500,
            pwm_prescaler=8,
            adc_ocr2a=79,
            adc_prescaler=8,
            samples=samples,
        )

        # Prepend 37 bytes of garbage and partial header
        corrupted_stream = b"GARBAGE_RANDOM_DATA_1234567\xAA" + valid_packet

        frames = list(parser.parse_stream(corrupted_stream))
        self.assertEqual(len(frames), 1)
        self.assertGreaterEqual(parser.sync_losses, 1)
        self.assertEqual(frames[0].timestamp_us, 10000)

    def test_storage_buffer_rollover(self):
        buf = StorageBuffer(capacity=1000)

        # Append 12 chunks of 100 samples = 1200 samples total
        for i in range(12):
            ts = np.arange(i * 100, (i + 1) * 100, dtype=np.float64) * 40e-6
            volt = np.full(100, float(i), dtype=np.float32)
            raw = np.full(100, i, dtype=np.uint16)
            buf.append(ts, volt, raw)

        self.assertEqual(buf.total_samples, 1200)
        self.assertEqual(buf.current_size, 1000)

        # Get latest 100 samples -> should be chunk 11 (values 11.0)
        ts_latest, v_latest = buf.get_latest(100)
        self.assertEqual(len(v_latest), 100)
        self.assertTrue(np.allclose(v_latest, 11.0))

        # Get all 1000 samples -> should start from sample index 200 (chunk 2) to 1199 (chunk 11)
        ts_all, v_all = buf.get_all()
        self.assertEqual(len(v_all), 1000)
        self.assertTrue(np.isclose(v_all[0], 2.0))
        self.assertTrue(np.isclose(v_all[-1], 11.0))


if __name__ == "__main__":
    unittest.main()
