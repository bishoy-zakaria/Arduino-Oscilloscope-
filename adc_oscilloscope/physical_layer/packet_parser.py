"""
Physical Layer: Packet Parser for Arduino Uno ADC DAQ stream.
Matches binary format emitted by arduinoUNO_ADC.ino.
"""

from dataclasses import dataclass
import struct
from typing import Generator, List, Optional, Tuple
import numpy as np

# Header sync bytes
SYNC_BYTE_0 = 0xAA
SYNC_BYTE_1 = 0x55
SYNC_HEADER = bytes([SYNC_BYTE_0, SYNC_BYTE_1])

# Payload format:
# uint32_t timestamp_us
# uint32_t f_cpu_hz
# uint16_t pwm_icr1
# uint16_t pwm_ocr1a
# uint16_t pwm_prescaler
# uint8_t  adc_ocr2a
# uint16_t adc_prescaler
# uint16_t samples[100]
SAMPLES_PER_PACKET = 100
PAYLOAD_FORMAT = f"<IIHHHBH{SAMPLES_PER_PACKET}H"
PAYLOAD_SIZE = struct.calcsize(PAYLOAD_FORMAT)  # 217 bytes
TOTAL_FRAME_SIZE = len(SYNC_HEADER) + PAYLOAD_SIZE  # 219 bytes


@dataclass
class AdcFrame:
    """Represents a single parsed packet from the Arduino Uno."""
    timestamp_us: int
    f_cpu_hz: int
    pwm_icr1: int
    pwm_ocr1a: int
    pwm_prescaler: int
    adc_ocr2a: int
    adc_prescaler: int
    raw_samples: np.ndarray  # uint16, length 100
    voltages: np.ndarray     # float32, length 100
    timestamps_s: np.ndarray # float64, length 100 (continuous monotonic seconds)


class StreamParser:
    """
    Stateful streaming frame synchronizer and parser.
    Extracts frames from continuous byte streams, recovers from desync,
    and maintains unwrapped continuous monotonic timestamps.
    """

    def __init__(self, vref: float = 5.0, adc_max_count: float = 1023.0):
        self.vref = float(vref)
        self.adc_max_count = float(adc_max_count)
        self.buffer = bytearray()

        # Telemetry / metrics
        self.total_frames_parsed = 0
        self.sync_losses = 0
        self.bytes_processed = 0

        # Monotonic sample index counter (guarantees zero backwards jumps)
        self._continuous_sample_count: int = 0
        self._prev_raw_micros: Optional[int] = None
        self._micros_wrap_offset: int = 0

    def reset(self) -> None:
        """Reset parser state and internal buffer."""
        self.buffer.clear()
        self._continuous_sample_count = 0
        self._prev_raw_micros = None
        self._micros_wrap_offset = 0

    def parse_stream(self, chunk: bytes) -> Generator[AdcFrame, None, None]:
        """
        Accepts a chunk of raw serial bytes and yields parsed AdcFrame objects.
        """
        if not chunk:
            return

        self.bytes_processed += len(chunk)
        self.buffer.extend(chunk)

        while True:
            # Need at least full frame size to proceed
            if len(self.buffer) < TOTAL_FRAME_SIZE:
                break

            # Search for sync header 0xAA 0x55
            sync_idx = self.buffer.find(SYNC_HEADER)

            if sync_idx == -1:
                # No sync header found in buffer.
                # Keep last 1 byte in case it's 0xAA of an incoming header.
                if len(self.buffer) > 0 and self.buffer[-1] == SYNC_BYTE_0:
                    del self.buffer[:-1]
                else:
                    self.buffer.clear()
                break

            if sync_idx > 0:
                # Dropped garbage bytes before sync header
                self.sync_losses += 1
                del self.buffer[:sync_idx]

            # Re-check length after discarding garbage
            if len(self.buffer) < TOTAL_FRAME_SIZE:
                break

            # Extract payload
            payload_bytes = self.buffer[len(SYNC_HEADER):TOTAL_FRAME_SIZE]
            del self.buffer[:TOTAL_FRAME_SIZE]

            frame = self._unpack_payload(payload_bytes)
            if frame is not None:
                self.total_frames_parsed += 1
                yield frame

    def _unpack_payload(self, payload_bytes: bytes) -> Optional[AdcFrame]:
        try:
            fields = struct.unpack(PAYLOAD_FORMAT, payload_bytes)
        except struct.error:
            self.sync_losses += 1
            return None

        raw_timestamp_us = fields[0]
        f_cpu_hz = fields[1]
        pwm_icr1 = fields[2]
        pwm_ocr1a = fields[3]
        pwm_prescaler = fields[4]
        adc_ocr2a = fields[5]
        adc_prescaler = fields[6]
        raw_samples = np.array(fields[7:], dtype=np.uint16)

        # Calculate sample interval in seconds
        # Timer2 ticks at f_cpu / adc_prescaler. Trigger interval = (adc_ocr2a + 1) ticks
        if f_cpu_hz > 0 and adc_prescaler > 0:
            sample_period_s = float(adc_ocr2a + 1) * float(adc_prescaler) / float(f_cpu_hz)
        else:
            sample_period_s = 40.0e-6  # Default fallback 40 us (25 kHz)

        # Generate strictly monotonic continuous timestamps based on sample index
        # Guaranteed to never jump backwards, wrap, or glitch
        indices = np.arange(SAMPLES_PER_PACKET, dtype=np.float64)
        timestamps_s = (self._continuous_sample_count + indices) * sample_period_s
        self._continuous_sample_count += SAMPLES_PER_PACKET

        # Convert raw ADC readings (0..1023) to Voltage (0..Vref)
        voltages = (raw_samples.astype(np.float32) * (self.vref / self.adc_max_count))

        return AdcFrame(
            timestamp_us=raw_timestamp_us,
            f_cpu_hz=f_cpu_hz,
            pwm_icr1=pwm_icr1,
            pwm_ocr1a=pwm_ocr1a,
            pwm_prescaler=pwm_prescaler,
            adc_ocr2a=adc_ocr2a,
            adc_prescaler=adc_prescaler,
            raw_samples=raw_samples,
            voltages=voltages,
            timestamps_s=timestamps_s
        )


def pack_adc_packet(
    timestamp_us: int,
    f_cpu_hz: int,
    pwm_icr1: int,
    pwm_ocr1a: int,
    pwm_prescaler: int,
    adc_ocr2a: int,
    adc_prescaler: int,
    samples: List[int]
) -> bytes:
    """Utility function to pack a binary packet (useful for simulator and unit testing)."""
    assert len(samples) == SAMPLES_PER_PACKET, f"Must provide {SAMPLES_PER_PACKET} samples"
    payload = struct.pack(
        PAYLOAD_FORMAT,
        timestamp_us,
        f_cpu_hz,
        pwm_icr1,
        pwm_ocr1a,
        pwm_prescaler,
        adc_ocr2a,
        adc_prescaler,
        *samples
    )
    return SYNC_HEADER + payload
