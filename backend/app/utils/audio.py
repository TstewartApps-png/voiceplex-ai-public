"""Audio processing utilities for voice handling."""

import base64
import struct
from typing import Generator


def pcm_to_mulaw(pcm_data: bytes) -> bytes:
    """
    Convert PCM audio to mu-law encoding for Twilio.

    Twilio expects 8kHz mu-law audio for media streams.

    Args:
        pcm_data: Raw PCM audio data (16-bit signed)

    Returns:
        Mu-law encoded audio data
    """
    MULAW_MAX = 0x1FFF
    MULAW_BIAS = 33

    mulaw_data = bytearray()

    # Process 16-bit samples
    for i in range(0, len(pcm_data), 2):
        if i + 1 >= len(pcm_data):
            break

        # Unpack as signed 16-bit
        sample = struct.unpack('<h', pcm_data[i:i+2])[0]

        # Get sign and magnitude
        sign = (sample >> 8) & 0x80
        if sign:
            sample = -sample

        # Add bias and clamp
        sample = min(sample + MULAW_BIAS, MULAW_MAX)

        # Find segment
        exponent = 7
        for exp in range(7, -1, -1):
            if sample >= (1 << (exp + 3)):
                exponent = exp
                break

        mantissa = (sample >> (exponent + 3)) & 0x0F
        mulaw_byte = ~(sign | (exponent << 4) | mantissa) & 0xFF
        mulaw_data.append(mulaw_byte)

    return bytes(mulaw_data)


def mulaw_to_pcm(mulaw_data: bytes) -> bytes:
    """
    Convert mu-law audio to PCM.

    Args:
        mulaw_data: Mu-law encoded audio

    Returns:
        PCM audio data (16-bit signed)
    """
    MULAW_BIAS = 33

    pcm_data = bytearray()

    for byte in mulaw_data:
        byte = ~byte & 0xFF
        sign = byte & 0x80
        exponent = (byte >> 4) & 0x07
        mantissa = byte & 0x0F

        sample = ((mantissa << 3) + MULAW_BIAS) << exponent
        sample -= MULAW_BIAS

        if sign:
            sample = -sample

        # Pack as signed 16-bit little-endian
        pcm_data.extend(struct.pack('<h', sample))

    return bytes(pcm_data)


def base64_to_audio(base64_audio: str) -> bytes:
    """
    Decode base64-encoded audio.

    Args:
        base64_audio: Base64 encoded audio string

    Returns:
        Raw audio bytes
    """
    return base64.b64decode(base64_audio)


def audio_to_base64(audio_data: bytes) -> str:
    """
    Encode audio to base64.

    Args:
        audio_data: Raw audio bytes

    Returns:
        Base64 encoded string
    """
    return base64.b64encode(audio_data).decode('utf-8')


def chunk_audio(
    audio_data: bytes,
    chunk_size: int = 640,
) -> Generator[bytes, None, None]:
    """
    Chunk audio data for streaming.

    Default chunk size of 640 bytes = 20ms of 8kHz 16-bit audio.

    Args:
        audio_data: Raw audio bytes
        chunk_size: Size of each chunk in bytes

    Yields:
        Audio chunks
    """
    for i in range(0, len(audio_data), chunk_size):
        yield audio_data[i:i + chunk_size]


def calculate_duration_seconds(
    audio_data: bytes,
    sample_rate: int = 8000,
    bits_per_sample: int = 8,
) -> float:
    """
    Calculate audio duration in seconds.

    Args:
        audio_data: Raw audio bytes
        sample_rate: Samples per second
        bits_per_sample: Bits per sample

    Returns:
        Duration in seconds
    """
    bytes_per_sample = bits_per_sample // 8
    total_samples = len(audio_data) // bytes_per_sample
    return total_samples / sample_rate
