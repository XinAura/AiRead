from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, cast

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from airead.core.config import get_settings
from airead.core.database import engine, get_db
from airead.modules.audio.schemas import AudioRenderView, CreateAudioRequest, CreateAudioResponse
from airead.modules.audio.service import AudioService
from airead.modules.documents.schemas import (
    ContentBlockView,
    ParsedDocumentDetail,
    ParsedDocumentView,
)
from airead.modules.editions.schemas import EditionView
from airead.modules.editions.service import EditionService
from airead.modules.jobs.schemas import PipelineRunView
from airead.modules.library.schemas import (
    ContentType,
    ImportResponse,
    LibraryItemDetail,
    LibraryItemView,
)
from airead.modules.library.service import LibraryService
from airead.modules.models import (
    AudioPartRecord,
    ParsedDocumentRecord,
    PipelineRunRecord,
    SourceDocumentRecord,
)
from airead.providers.storage import ObjectStorage, build_storage
from airead.providers.tts import build_tts_provider
from airead.workers.audio import render_audio_part_task
from airead.workers.parsing import parse_source_task

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.storage = build_storage(settings)
    yield


app = FastAPI(title="AiRead API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=(
        settings.development_cors_origin_regex if settings.env == "development" else None
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DbSession = Annotated[Session, Depends(get_db)]


def get_storage(request: Request) -> ObjectStorage:
    return cast(ObjectStorage, request.app.state.storage)


Storage = Annotated[ObjectStorage, Depends(get_storage)]


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "tts_provider": settings.tts_provider}


@app.get("/readyz")
def readyz(storage: Storage) -> dict[str, str]:
    failures: list[str] = []
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        failures.append("postgres")
    try:
        client = Redis.from_url(settings.redis_url, socket_timeout=1)
        client.ping()
        client.close()
    except Exception:
        failures.append("redis")
    try:
        probe = storage.put("health/ready.txt", b"ready", "text/plain")
        if storage.read(probe.key) != b"ready":
            failures.append("storage")
    except Exception:
        failures.append("storage")
    if failures:
        raise HTTPException(status_code=503, detail={"unavailable": failures})
    return {"status": "ready"}


@app.post("/library/items", response_model=ImportResponse, status_code=status.HTTP_202_ACCEPTED)
async def import_library_item(
    db: DbSession,
    storage: Storage,
    title: Annotated[str, Form(min_length=1, max_length=500)],
    content_type: Annotated[ContentType, Form()] = "unknown",
    author: Annotated[str | None, Form(max_length=300)] = None,
    file: Annotated[UploadFile | None, File()] = None,
    pasted_text: Annotated[str | None, Form()] = None,
) -> ImportResponse:
    if (file is None) == (pasted_text is None):
        raise HTTPException(status_code=422, detail="必须且只能提供文件或粘贴文本")
    if file is not None:
        payload = await file.read()
        filename = file.filename or "document.txt"
        mime_type = file.content_type
    else:
        payload = (pasted_text or "").encode("utf-8")
        filename = "pasted.txt"
        mime_type = "text/plain"
    try:
        item, source, run = LibraryService(db, storage).import_file(
            title=title,
            author=author,
            content_type=content_type,
            filename=filename,
            mime_type=mime_type,
            payload=payload,
        )
        parse_source_task.delay(source.id, run.id)
        return ImportResponse(item=item, source=source, run_id=run.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/library/items", response_model=list[LibraryItemView])
def list_library_items(db: DbSession, storage: Storage) -> list[LibraryItemView]:
    return [
        LibraryItemView.model_validate(item) for item in LibraryService(db, storage).list_items()
    ]


@app.get("/library/items/{item_id}", response_model=LibraryItemDetail)
def get_library_item(item_id: str, db: DbSession, storage: Storage) -> LibraryItemDetail:
    try:
        return LibraryItemDetail.model_validate(LibraryService(db, storage).get_item(item_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/library/items/{item_id}/editions", response_model=list[EditionView])
def list_editions(item_id: str, db: DbSession) -> list[EditionView]:
    return [EditionView.model_validate(item) for item in EditionService(db).list_for_item(item_id)]


@app.post(
    "/documents/{source_id}/parse",
    response_model=PipelineRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
def parse_document(source_id: str, db: DbSession) -> PipelineRunView:
    source = db.get(SourceDocumentRecord, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="原始资料不存在")
    run = PipelineRunRecord(
        run_type="ingestion_parse",
        root_entity_type="source_document",
        root_entity_id=source.id,
    )
    db.add(run)
    db.flush()
    from airead.modules.models import TaskNodeRecord

    db.add(
        TaskNodeRecord(
            run_id=run.id,
            node_type="parse_source",
            input_hash=source.content_hash,
            idempotency_key=f"parse:{source.id}:{run.id}",
        )
    )
    db.commit()
    parse_source_task.delay(source.id, run.id)
    return _get_run(db, run.id)


@app.get("/documents/{document_id}", response_model=ParsedDocumentDetail)
def get_document(document_id: str, db: DbSession) -> ParsedDocumentDetail:
    document = db.scalar(
        select(ParsedDocumentRecord)
        .where(ParsedDocumentRecord.id == document_id)
        .options(selectinload(ParsedDocumentRecord.blocks))
    )
    if document is None:
        raise HTTPException(status_code=404, detail="结构化文档不存在")
    return ParsedDocumentDetail.model_validate(document)


@app.get("/sources/{source_id}/documents", response_model=list[ParsedDocumentView])
def list_source_documents(source_id: str, db: DbSession) -> list[ParsedDocumentView]:
    source = db.get(SourceDocumentRecord, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="原始资料不存在")
    documents = db.scalars(
        select(ParsedDocumentRecord)
        .where(ParsedDocumentRecord.source_document_id == source_id)
        .order_by(ParsedDocumentRecord.created_at.desc())
    )
    return [ParsedDocumentView.model_validate(document) for document in documents]


@app.get("/documents/{document_id}/blocks", response_model=list[ContentBlockView])
def get_document_blocks(document_id: str, db: DbSession) -> list[ContentBlockView]:
    document = db.scalar(
        select(ParsedDocumentRecord)
        .where(ParsedDocumentRecord.id == document_id)
        .options(selectinload(ParsedDocumentRecord.blocks))
    )
    if document is None:
        raise HTTPException(status_code=404, detail="结构化文档不存在")
    return [ContentBlockView.model_validate(block) for block in document.blocks]


@app.get("/documents/{document_id}/chapters", response_model=list[ContentBlockView])
def get_document_chapters(document_id: str, db: DbSession) -> list[ContentBlockView]:
    document = db.get(ParsedDocumentRecord, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="结构化文档不存在")
    from airead.modules.models import ContentBlockRecord

    blocks = db.scalars(
        select(ContentBlockRecord)
        .where(
            ContentBlockRecord.parsed_document_id == document_id,
            ContentBlockRecord.block_type.in_(["volume", "chapter"]),
        )
        .order_by(ContentBlockRecord.position)
    )
    return [ContentBlockView.model_validate(block) for block in blocks]


@app.get("/editions/{edition_id}", response_model=EditionView)
def get_edition(edition_id: str, db: DbSession) -> EditionView:
    try:
        return EditionView.model_validate(EditionService(db).get(edition_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/editions/{edition_id}/audio",
    response_model=CreateAudioResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_audio(
    edition_id: str, request: CreateAudioRequest, db: DbSession, storage: Storage
) -> CreateAudioResponse:
    service = AudioService(db, storage, build_tts_provider(settings), settings)
    try:
        render, run = service.create_render(edition_id, request.voice, request.rate, request.pitch)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for part in render.parts:
        if part.batch_index != 0:
            continue
        render_audio_part_task.delay(part.id, run.id)
    return CreateAudioResponse(render=AudioRenderView.model_validate(render), run_id=run.id)


@app.get("/audio-renders/{render_id}", response_model=AudioRenderView)
def get_audio_render(render_id: str, db: DbSession, storage: Storage) -> AudioRenderView:
    try:
        service = AudioService(db, storage, build_tts_provider(settings), settings)
        return AudioRenderView.model_validate(service.get_render(render_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/editions/{edition_id}/audio-renders", response_model=list[AudioRenderView])
def list_audio_renders(edition_id: str, db: DbSession, storage: Storage) -> list[AudioRenderView]:
    from airead.modules.models import AudioRenderRecord

    renders = db.scalars(
        select(AudioRenderRecord)
        .where(AudioRenderRecord.edition_id == edition_id)
        .options(selectinload(AudioRenderRecord.parts).selectinload(AudioPartRecord.chunks))
        .order_by(AudioRenderRecord.created_at.desc())
    )
    return [AudioRenderView.model_validate(render) for render in renders]


@app.post("/audio-parts/{part_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_audio_part(part_id: str, db: DbSession, storage: Storage) -> dict[str, str]:
    service = AudioService(db, storage, build_tts_provider(settings), settings)
    try:
        part, run_id = service.retry_part(part_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    render_audio_part_task.delay(part.id, run_id)
    return {"part_id": part.id, "run_id": run_id, "status": "pending"}


@app.get("/audio-parts/{part_id}/stream")
def stream_audio_part(part_id: str, request: Request, db: DbSession, storage: Storage) -> Response:
    service = AudioService(db, storage, build_tts_provider(settings), settings)
    try:
        asset = service.get_part_asset(part_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = storage.read(asset.storage_key)
    range_header = request.headers.get("range")
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    if not range_header:
        headers["Content-Length"] = str(len(payload))
        return StreamingResponse(iter([payload]), media_type=asset.mime_type, headers=headers)
    start, end = _parse_range(range_header, len(payload))
    partial = payload[start : end + 1]
    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{len(payload)}",
            "Content-Length": str(len(partial)),
        }
    )
    return StreamingResponse(
        iter([partial]), status_code=206, media_type=asset.mime_type, headers=headers
    )


@app.get("/jobs/{run_id}", response_model=PipelineRunView)
def get_job(run_id: str, db: DbSession) -> PipelineRunView:
    try:
        return _get_run(db, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _get_run(db: Session, run_id: str) -> PipelineRunView:
    run = db.scalar(
        select(PipelineRunRecord)
        .where(PipelineRunRecord.id == run_id)
        .options(selectinload(PipelineRunRecord.nodes))
    )
    if run is None:
        raise LookupError("任务不存在")
    return PipelineRunView.model_validate(run)


def _parse_range(value: str, total: int) -> tuple[int, int]:
    try:
        unit, bounds = value.strip().split("=", 1)
        if unit != "bytes" or "," in bounds:
            raise ValueError
        start_text, end_text = bounds.split("-", 1)
        if not start_text:
            length = int(end_text)
            if length <= 0:
                raise ValueError
            return max(0, total - length), total - 1
        start = int(start_text)
        end = int(end_text) if end_text else total - 1
        if start < 0 or start >= total or end < start:
            raise ValueError
        return start, min(end, total - 1)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=416,
            detail="无效的音频范围",
            headers={"Content-Range": f"bytes */{total}"},
        ) from None
