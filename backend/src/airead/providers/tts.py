from __future__ import annotations

import asyncio
import io
import math
import struct
import wave
from dataclasses import dataclass
from typing import Protocol

import edge_tts

from airead.core.config import Settings, get_settings


@dataclass(frozen=True)
class TtsAudio:
    payload: bytes
    mime_type: str
    extension: str


class TtsProvider(Protocol):
    name: str
    version: str

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> TtsAudio: ...


class EdgeTtsProvider:
    name = "edge"
    version = edge_tts.__version__

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> TtsAudio:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        payload = bytearray()
        async for message in communicate.stream():
            if message["type"] == "audio":
                payload.extend(message["data"])
        if not payload:
            raise RuntimeError("Edge TTS 未返回音频")
        return TtsAudio(bytes(payload), "audio/mpeg", ".mp3")


class MockTtsProvider:
    name = "mock"
    version = "1"

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> TtsAudio:
        del voice, rate, pitch
        await asyncio.sleep(0)
        duration = max(0.15, min(2.0, len(text) * 0.015))
        sample_rate = 16_000
        frames = int(sample_rate * duration)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            for index in range(frames):
                value = int(800 * math.sin(2 * math.pi * 220 * index / sample_rate))
                output.writeframesraw(struct.pack("<h", value))
        return TtsAudio(buffer.getvalue(), "audio/wav", ".wav")


def build_tts_provider(settings: Settings | None = None) -> TtsProvider:
    settings = settings or get_settings()
    if settings.tts_provider == "mock":
        return MockTtsProvider()
    return EdgeTtsProvider()
