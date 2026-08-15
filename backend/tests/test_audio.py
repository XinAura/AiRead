from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from airead.core.config import Settings
from airead.modules.audio.service import (
    AudioService,
    RetryableAudioError,
    build_cache_key,
    split_text,
)
from airead.modules.editions.service import EditionService
from airead.modules.library.service import LibraryService
from airead.modules.models import AudioChunkRecord, TaskNodeRecord, TtsCacheRecord
from airead.modules.parsing.service import ParsingService
from airead.providers.storage import LocalObjectStorage
from airead.providers.tts import MockTtsProvider, TtsAudio


class TemporaryFailureTtsProvider:
    name = "temporary-failure"
    version = "1"

    async def synthesize(self, text: str, voice: str, rate: str, pitch: str) -> TtsAudio:
        del text, voice, rate, pitch
        raise TimeoutError("temporary TTS timeout")


def make_edition(session: Session, storage: LocalObjectStorage) -> str:
    _, source, run = LibraryService(session, storage).import_file(
        title="短篇",
        author=None,
        content_type="novel",
        filename="short.txt",
        mime_type="text/plain",
        payload="第一章 开始\n\n这是第一章。\n\n第二章 继续\n\n这是第二章。".encode(),
    )
    document = ParsingService(session, storage).parse(source.id, run.id)
    return EditionService(session).create_original(document.id).id


def test_audio_parts_render_independently_and_reuse_chunk_cache(
    session: Session, tmp_path: Path
) -> None:
    storage = LocalObjectStorage(tmp_path)
    edition_id = make_edition(session, storage)
    settings = Settings(
        storage_root=tmp_path,
        tts_provider="mock",
        ffmpeg_path="/home/xin/.local/bin/ffmpeg",
        ffprobe_path="/home/xin/.local/bin/ffprobe",
    )
    service = AudioService(session, storage, MockTtsProvider(), settings)
    render, run = service.create_render(edition_id, "mock-voice", "+0%", "+0Hz")

    first = service.render_part(render.parts[0].id, run.id)

    assert first.status == "succeeded"
    assert first.duration_ms and first.duration_ms > 0
    assert first.audio_asset_id
    assert render.parts[1].status == "pending"
    cache_count = session.scalar(select(func.count()).select_from(TtsCacheRecord))
    assert cache_count == len(first.chunks)

    second_render, second_run = service.create_render(edition_id, "mock-voice", "+0%", "+0Hz")
    repeated = service.render_part(second_render.parts[0].id, second_run.id)

    assert repeated.status == "succeeded"
    assert session.scalar(select(func.count()).select_from(TtsCacheRecord)) == cache_count
    assert all(chunk.attempt_count == 0 for chunk in repeated.chunks)


def test_retry_resets_only_selected_part(session: Session, tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    edition_id = make_edition(session, storage)
    settings = Settings(storage_root=tmp_path, tts_provider="mock")
    service = AudioService(session, storage, MockTtsProvider(), settings)
    render, run = service.create_render(edition_id, "voice", "+0%", "+0Hz")
    failed = render.parts[0]
    failed.status = "failed"
    failed.error_code = "network"
    render.parts[1].status = "succeeded"
    session.commit()

    reset, reset_run_id = service.retry_part(failed.id)

    assert reset_run_id == run.id
    assert reset.status == "pending"
    assert reset.retry_count == 1
    assert reset.error_code is None
    assert render.parts[1].status == "succeeded"


def test_render_releases_only_next_batch_after_current_batch_finishes(
    session: Session, tmp_path: Path
) -> None:
    storage = LocalObjectStorage(tmp_path)
    edition_id = make_edition(session, storage)
    settings = Settings(
        storage_root=tmp_path,
        tts_provider="mock",
        audio_batch_size=1,
        ffmpeg_path="/home/xin/.local/bin/ffmpeg",
        ffprobe_path="/home/xin/.local/bin/ffprobe",
    )
    service = AudioService(session, storage, MockTtsProvider(), settings)
    render, run = service.create_render(edition_id, "voice", "+0%", "+0Hz")

    assert render.batch_size == 1
    assert render.batch_count == 2
    assert [part.batch_index for part in render.parts] == [0, 1]
    assert service.claim_next_batch(render.parts[0].id, run.id) == []

    service.render_part(render.parts[0].id, run.id)
    next_part_ids = service.claim_next_batch(render.parts[0].id, run.id)

    assert next_part_ids == [render.parts[1].id]
    session.refresh(render)
    assert render.next_batch_index == 2
    assert service.claim_next_batch(render.parts[0].id, run.id) == []


def test_render_partitions_seven_chapters_into_three_ordered_batches(
    session: Session, tmp_path: Path
) -> None:
    storage = LocalObjectStorage(tmp_path)
    chapter_text = "\n".join(f"第{index}章 标题{index}\n正文{index}。" for index in range(1, 8))
    _, source, parse_run = LibraryService(session, storage).import_file(
        title="七章小说",
        author=None,
        content_type="novel",
        filename="seven.txt",
        mime_type="text/plain",
        payload=chapter_text.encode(),
    )
    document = ParsingService(session, storage).parse(source.id, parse_run.id)
    edition_id = EditionService(session).create_original(document.id).id
    settings = Settings(storage_root=tmp_path, tts_provider="mock", audio_batch_size=3)
    service = AudioService(session, storage, MockTtsProvider(), settings)

    render, run = service.create_render(edition_id, "voice", "+0%", "+0Hz")

    assert render.batch_count == 3
    assert [part.batch_index for part in render.parts] == [0, 0, 0, 1, 1, 1, 2]
    for part in render.parts[:3]:
        part.status = "succeeded"
    session.commit()
    assert service.claim_next_batch(render.parts[2].id, run.id) == [
        part.id for part in render.parts[3:6]
    ]
    for part in render.parts[3:6]:
        part.status = "succeeded"
    session.commit()
    assert service.claim_next_batch(render.parts[5].id, run.id) == [render.parts[6].id]


def test_temporary_tts_failure_marks_chunk_and_node_retryable(
    session: Session, tmp_path: Path
) -> None:
    storage = LocalObjectStorage(tmp_path)
    edition_id = make_edition(session, storage)
    settings = Settings(storage_root=tmp_path, tts_provider="mock")
    service = AudioService(session, storage, TemporaryFailureTtsProvider(), settings)
    render, run = service.create_render(edition_id, "voice", "+0%", "+0Hz")

    with pytest.raises(RetryableAudioError):
        service.render_part(render.parts[0].id, run.id)

    session.refresh(render.parts[0])
    assert render.parts[0].status == "retryable"
    assert render.parts[0].chunks[0].status == "retryable"
    node = session.scalar(
        select(TaskNodeRecord).where(
            TaskNodeRecord.run_id == run.id,
            TaskNodeRecord.idempotency_key == f"audio-part:{render.parts[0].id}",
        )
    )
    assert node is not None
    assert node.status == "retryable"
    assert service.claim_next_batch(render.parts[0].id, run.id) == []


def test_split_and_cache_key_include_all_voice_parameters() -> None:
    chunks = split_text("第一段。\n" + "字" * 1700, max_length=1000)
    assert all(0 < len(chunk) <= 1000 for chunk in chunks)
    base = build_cache_key("文本", "voice-a", "+0%", "+0Hz", "edge", "1")
    assert base != build_cache_key("文本", "voice-b", "+0%", "+0Hz", "edge", "1")
    assert base != build_cache_key("文本", "voice-a", "+10%", "+0Hz", "edge", "1")
    assert base != build_cache_key("文本", "voice-a", "+0%", "+0Hz", "edge", "2")


def test_chunk_rows_keep_source_references(session: Session, tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    edition_id = make_edition(session, storage)
    service = AudioService(
        session, storage, MockTtsProvider(), Settings(storage_root=tmp_path, tts_provider="mock")
    )
    render, _ = service.create_render(edition_id, "voice", "+0%", "+0Hz")

    chunks = list(
        session.scalars(
            select(AudioChunkRecord).where(AudioChunkRecord.audio_part_id == render.parts[0].id)
        )
    )
    assert chunks
    assert all(chunk.source_block_ids for chunk in chunks)
