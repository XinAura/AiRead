from __future__ import annotations

import asyncio
import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path

from aiohttp import ClientError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from airead.core.config import Settings
from airead.modules.models import (
    AssetRecord,
    AudioChunkRecord,
    AudioPartRecord,
    AudioRenderRecord,
    EditionRecord,
    PipelineRunRecord,
    TaskNodeRecord,
    TtsCacheRecord,
    utcnow,
)
from airead.providers.limits import NoopSlotLimiter, SlotLimiter
from airead.providers.storage import ObjectStorage
from airead.providers.tts import TtsAudio, TtsProvider

MAX_CHUNK_LENGTH = 1600


class RetryableAudioError(RuntimeError):
    pass


class AudioService:
    def __init__(
        self,
        session: Session,
        storage: ObjectStorage,
        tts: TtsProvider,
        settings: Settings,
        *,
        render_limiter: SlotLimiter | None = None,
        tts_limiter: SlotLimiter | None = None,
        assemble_limiter: SlotLimiter | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.tts = tts
        self.settings = settings
        self.render_limiter = render_limiter or NoopSlotLimiter()
        self.tts_limiter = tts_limiter or NoopSlotLimiter()
        self.assemble_limiter = assemble_limiter or NoopSlotLimiter()

    def create_render(
        self, edition_id: str, voice: str, rate: str, pitch: str
    ) -> tuple[AudioRenderRecord, PipelineRunRecord]:
        edition = self.session.scalar(
            select(EditionRecord)
            .where(EditionRecord.id == edition_id)
            .options(selectinload(EditionRecord.blocks))
        )
        if edition is None:
            raise LookupError("朗读版本不存在")
        batch_size = self.settings.audio_batch_size
        batch_count = max(1, math.ceil(len(edition.blocks) / batch_size))
        render = AudioRenderRecord(
            edition_id=edition.id,
            voice=voice,
            rate=rate,
            pitch=pitch,
            provider=self.tts.name,
            provider_version=self.tts.version,
            batch_size=batch_size,
            batch_count=batch_count,
            next_batch_index=1,
        )
        self.session.add(render)
        self.session.flush()
        run = PipelineRunRecord(
            run_type="audio_render",
            root_entity_type="audio_render",
            root_entity_id=render.id,
        )
        self.session.add(run)
        self.session.flush()
        for block in edition.blocks:
            part = AudioPartRecord(
                audio_render_id=render.id,
                edition_block_id=block.id,
                position=block.position,
                batch_index=block.position // batch_size,
                title=block.section_title or f"第 {block.position + 1} 部分",
            )
            self.session.add(part)
            self.session.flush()
            for chunk_position, text in enumerate(split_text(block.text)):
                cache_key = build_cache_key(
                    text, voice, rate, pitch, self.tts.name, self.tts.version
                )
                self.session.add(
                    AudioChunkRecord(
                        audio_part_id=part.id,
                        position=chunk_position,
                        text=text,
                        source_block_ids=block.source_block_ids,
                        cache_key=cache_key,
                    )
                )
            self.session.add(
                TaskNodeRecord(
                    run_id=run.id,
                    node_type="render_audio_part",
                    input_hash=hashlib.sha256(block.text.encode()).hexdigest(),
                    idempotency_key=f"audio-part:{part.id}",
                    max_attempts=3,
                )
            )
        self.session.commit()
        return self.get_render(render.id), run

    def claim_next_batch(self, part_id: str, run_id: str) -> list[str]:
        part = self.session.get(AudioPartRecord, part_id)
        if part is None:
            raise LookupError("音频章节不存在")
        render = self.session.scalar(
            select(AudioRenderRecord)
            .where(AudioRenderRecord.id == part.audio_render_id)
            .with_for_update()
        )
        if render is None:
            raise LookupError("音频任务不存在")
        run = self.session.get(PipelineRunRecord, run_id)
        if run is None or run.root_entity_type != "audio_render" or run.root_entity_id != render.id:
            raise LookupError("音频流水线与章节不匹配")
        if render.status == "canceled":
            self.session.commit()
            return []

        current_batch = render.next_batch_index - 1
        current_statuses = list(
            self.session.scalars(
                select(AudioPartRecord.status).where(
                    AudioPartRecord.audio_render_id == render.id,
                    AudioPartRecord.batch_index == current_batch,
                )
            )
        )
        if not current_statuses or any(
            status not in {"succeeded", "failed"} for status in current_statuses
        ):
            self.session.commit()
            return []

        next_batch = render.next_batch_index
        if next_batch >= render.batch_count:
            self.session.commit()
            return []
        part_ids = list(
            self.session.scalars(
                select(AudioPartRecord.id)
                .where(
                    AudioPartRecord.audio_render_id == render.id,
                    AudioPartRecord.batch_index == next_batch,
                    AudioPartRecord.status == "pending",
                )
                .order_by(AudioPartRecord.position)
            )
        )
        render.next_batch_index += 1
        self.session.commit()
        return part_ids

    def render_part(self, part_id: str, run_id: str) -> AudioPartRecord:
        with self.render_limiter.hold():
            return self._render_part(part_id, run_id)

    def _render_part(self, part_id: str, run_id: str) -> AudioPartRecord:
        part = self.session.scalar(
            select(AudioPartRecord)
            .where(AudioPartRecord.id == part_id)
            .options(selectinload(AudioPartRecord.chunks), selectinload(AudioPartRecord.render))
        )
        if part is None:
            raise LookupError("音频章节不存在")
        if part.status == "canceled" or part.render.status == "canceled":
            return part
        node = self.session.scalar(
            select(TaskNodeRecord).where(
                TaskNodeRecord.run_id == run_id,
                TaskNodeRecord.idempotency_key == f"audio-part:{part.id}",
            )
        )
        if node is None:
            raise LookupError("音频任务节点不存在")
        if part.status == "succeeded" and part.audio_asset_id:
            return part
        part.status = "running"
        node.status = "running"
        node.attempt_count += 1
        node.started_at = node.started_at or utcnow()
        node.heartbeat_at = utcnow()
        part.render.status = "running"
        self.session.commit()
        try:
            asyncio.run(self._render_chunks(part))
            self.session.refresh(part)
            with self.assemble_limiter.hold():
                output, duration_ms = self._assemble(part)
            key = f"audio/renders/{part.audio_render_id}/parts/{part.position:05d}.mp3"
            stored = self.storage.put(key, output, "audio/mpeg")
            asset = AssetRecord(
                kind="audio_part",
                storage_key=stored.key,
                mime_type="audio/mpeg",
                byte_size=stored.byte_size,
                content_hash=stored.content_hash,
            )
            self.session.add(asset)
            self.session.flush()
            part.audio_asset_id = asset.id
            part.duration_ms = duration_ms
            part.status = "succeeded"
            node.status = "succeeded"
            node.progress = 100
            node.finished_at = utcnow()
            self._refresh_render_status(part.render, run_id)
            self.session.commit()
            return part
        except Exception as exc:
            can_retry = _is_retryable_audio_error(exc) and node.attempt_count < node.max_attempts
            part.status = "retryable" if can_retry else "failed"
            part.error_code = "audio_part_failed"
            part.error_message = str(exc)[:2000]
            node.status = "retryable" if can_retry else "failed"
            node.error_code = part.error_code
            node.error_message = part.error_message
            node.finished_at = utcnow()
            self._refresh_render_status(part.render, run_id)
            self.session.commit()
            raise

    async def _render_chunks(self, part: AudioPartRecord) -> None:
        semaphore = asyncio.Semaphore(self.settings.tts_chunk_concurrency)
        missing: list[AudioChunkRecord] = []

        for chunk in part.chunks:
            if chunk.status == "succeeded" and chunk.audio_asset_id:
                continue
            cache = self.session.scalar(
                select(TtsCacheRecord).where(TtsCacheRecord.cache_key == chunk.cache_key)
            )
            if cache is not None:
                chunk.audio_asset_id = cache.audio_asset_id
                chunk.duration_ms = cache.duration_ms
                chunk.status = "succeeded"
            else:
                chunk.status = "running"
                chunk.attempt_count += 1
                chunk.error_code = None
                chunk.error_message = None
                missing.append(chunk)
        self.session.commit()

        async def synthesize(chunk: AudioChunkRecord) -> tuple[AudioChunkRecord, TtsAudio]:
            async with semaphore, self.tts_limiter.hold_async():
                audio = await self.tts.synthesize(
                    chunk.text,
                    part.render.voice,
                    part.render.rate,
                    part.render.pitch,
                )
                return chunk, audio

        results = await asyncio.gather(
            *(synthesize(chunk) for chunk in missing), return_exceptions=True
        )
        errors: list[BaseException] = []
        for chunk, result in zip(missing, results, strict=True):
            if isinstance(result, BaseException):
                retryable = _is_retryable_audio_error(result)
                chunk.status = "retryable" if retryable and chunk.attempt_count < 3 else "failed"
                chunk.error_code = "tts_temporary" if retryable else "tts_invalid_request"
                chunk.error_message = str(result)[:2000]
                errors.append(result)
                continue
            _, audio = result
            key = f"audio/cache/{chunk.cache_key}{audio.extension}"
            stored = self.storage.put(key, audio.payload, audio.mime_type)
            asset = AssetRecord(
                kind="audio_chunk",
                storage_key=stored.key,
                mime_type=audio.mime_type,
                byte_size=stored.byte_size,
                content_hash=stored.content_hash,
            )
            self.session.add(asset)
            self.session.flush()
            duration = self._probe_bytes(audio.payload, audio.extension)
            self.session.add(
                TtsCacheRecord(
                    cache_key=chunk.cache_key,
                    audio_asset_id=asset.id,
                    duration_ms=duration,
                    provider=self.tts.name,
                    provider_version=self.tts.version,
                )
            )
            chunk.audio_asset_id = asset.id
            chunk.duration_ms = duration
            chunk.status = "succeeded"
        self.session.commit()
        if errors:
            if all(_is_retryable_audio_error(error) for error in errors):
                raise RetryableAudioError(str(errors[0]))
            raise RuntimeError(str(errors[0]))

    def _assemble(self, part: AudioPartRecord) -> tuple[bytes, int]:
        with tempfile.TemporaryDirectory(prefix="airead-") as directory:
            root = Path(directory)
            inputs: list[Path] = []
            for chunk in sorted(part.chunks, key=lambda item: item.position):
                if not chunk.audio_asset_id:
                    raise RuntimeError(f"音频分片 {chunk.position} 没有产物")
                asset = self.session.get(AssetRecord, chunk.audio_asset_id)
                if asset is None:
                    raise RuntimeError(f"音频分片 {chunk.position} 的资源不存在")
                suffix = ".mp3" if asset.mime_type == "audio/mpeg" else ".wav"
                path = root / f"{chunk.position:05d}{suffix}"
                path.write_bytes(self.storage.read(asset.storage_key))
                inputs.append(path)
            concat_file = root / "concat.txt"
            concat_file.write_text(
                "\n".join(f"file '{path.as_posix()}'" for path in inputs), encoding="utf-8"
            )
            output = root / "part.mp3"
            command = [
                self.settings.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "64k",
                "-y",
                str(output),
            ]
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=180, check=False
            )
            if completed.returncode != 0:
                raise RuntimeError(f"FFmpeg 拼接失败: {completed.stderr[-1000:]}")
            payload = output.read_bytes()
            return payload, self._probe_file(output)

    def _probe_bytes(self, payload: bytes, extension: str) -> int:
        with tempfile.NamedTemporaryFile(suffix=extension) as temporary:
            temporary.write(payload)
            temporary.flush()
            return self._probe_file(Path(temporary.name))

    def _probe_file(self, path: Path) -> int:
        completed = subprocess.run(
            [
                self.settings.ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"FFprobe 校验失败: {completed.stderr[-500:]}")
        duration = float(json.loads(completed.stdout)["format"]["duration"])
        return max(1, round(duration * 1000))

    def retry_part(self, part_id: str) -> tuple[AudioPartRecord, str]:
        part = self.session.get(AudioPartRecord, part_id)
        if part is None:
            raise LookupError("音频章节不存在")
        render = self.session.get(AudioRenderRecord, part.audio_render_id)
        if render is None or render.status == "canceled":
            raise LookupError("音频任务已取消")
        run = self.session.scalar(
            select(PipelineRunRecord).where(
                PipelineRunRecord.root_entity_type == "audio_render",
                PipelineRunRecord.root_entity_id == part.audio_render_id,
            )
        )
        if run is None:
            raise LookupError("音频任务不存在")
        part.retry_count += 1
        part.status = "pending"
        part.error_code = None
        part.error_message = None
        node = self.session.scalar(
            select(TaskNodeRecord).where(
                TaskNodeRecord.run_id == run.id,
                TaskNodeRecord.idempotency_key == f"audio-part:{part.id}",
            )
        )
        if node is not None:
            node.status = "pending"
            node.error_code = None
            node.error_message = None
        self.session.commit()
        return part, run.id

    def get_render(self, render_id: str) -> AudioRenderRecord:
        render = self.session.scalar(
            select(AudioRenderRecord)
            .where(AudioRenderRecord.id == render_id)
            .options(selectinload(AudioRenderRecord.parts).selectinload(AudioPartRecord.chunks))
        )
        if render is None:
            raise LookupError("音频任务不存在")
        return render

    def get_part_asset(self, part_id: str) -> AssetRecord:
        part = self.session.get(AudioPartRecord, part_id)
        if part is None or part.status != "succeeded" or not part.audio_asset_id:
            raise LookupError("章节音频尚不可播放")
        asset = self.session.get(AssetRecord, part.audio_asset_id)
        if asset is None:
            raise LookupError("章节音频资源不存在")
        return asset

    def _refresh_render_status(self, render: AudioRenderRecord, run_id: str) -> None:
        statuses = list(
            self.session.scalars(
                select(AudioPartRecord.status).where(AudioPartRecord.audio_render_id == render.id)
            )
        )
        run = self.session.get(PipelineRunRecord, run_id)
        completed = sum(status in {"succeeded", "failed"} for status in statuses)
        if run is not None:
            run.progress = round(completed / len(statuses) * 100) if statuses else 0
        if statuses and all(status == "succeeded" for status in statuses):
            render.status = "succeeded"
            if run is not None:
                run.status = "succeeded"
        elif statuses and all(status in {"succeeded", "failed"} for status in statuses):
            render.status = "partial_failed"
            if run is not None:
                run.status = "failed"
        else:
            render.status = "running"
            if run is not None:
                run.status = "running"


def split_text(text: str, max_length: int = MAX_CHUNK_LENGTH) -> list[str]:
    paragraphs = [item.strip() for item in text.split("\n") if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = [
            paragraph[index : index + max_length] for index in range(0, len(paragraph), max_length)
        ]
        for piece in pieces:
            if current and len(current) + len(piece) + 1 > max_length:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n{piece}".strip()
    if current:
        chunks.append(current)
    if not chunks:
        raise ValueError("朗读文本不能为空")
    return chunks


def build_cache_key(
    text: str, voice: str, rate: str, pitch: str, provider: str, provider_version: str
) -> str:
    value = "\0".join((text, voice, rate, pitch, provider, provider_version))
    return hashlib.sha256(value.encode()).hexdigest()


def _is_retryable_audio_error(error: BaseException) -> bool:
    if isinstance(error, (RetryableAudioError, TimeoutError, ConnectionError, ClientError)):
        return True
    message = str(error).lower()
    return any(marker in message for marker in ("429", "websocket", "connection", " 5"))
