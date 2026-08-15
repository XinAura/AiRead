from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from airead.modules.models import (
    AssetRecord,
    LibraryItemRecord,
    PipelineRunRecord,
    SourceDocumentRecord,
    TaskNodeRecord,
)
from airead.providers.storage import ObjectStorage


class DuplicateSourceError(ValueError):
    pass


class LibraryService:
    def __init__(self, session: Session, storage: ObjectStorage) -> None:
        self.session = session
        self.storage = storage

    def import_file(
        self,
        *,
        title: str,
        author: str | None,
        content_type: str,
        filename: str,
        mime_type: str | None,
        payload: bytes,
    ) -> tuple[LibraryItemRecord, SourceDocumentRecord, PipelineRunRecord]:
        if not payload:
            raise ValueError("上传文件不能为空")
        safe_name = Path(filename).name or "document.txt"
        resolved_mime = (
            mime_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        )
        digest = hashlib.sha256(payload).hexdigest()
        item = LibraryItemRecord(
            title=title.strip(), author=author or None, content_type=content_type
        )
        self.session.add(item)
        self.session.flush()

        key = f"sources/{item.id}/{digest[:16]}-{safe_name}"
        stored = self.storage.put(key, payload, resolved_mime)
        asset = AssetRecord(
            kind="source",
            storage_key=stored.key,
            mime_type=resolved_mime,
            byte_size=stored.byte_size,
            content_hash=stored.content_hash,
        )
        self.session.add(asset)
        self.session.flush()
        source = SourceDocumentRecord(
            library_item_id=item.id,
            source_type=_source_type(safe_name, resolved_mime),
            original_filename=safe_name,
            mime_type=resolved_mime,
            content_hash=digest,
            asset_id=asset.id,
        )
        self.session.add(source)
        self.session.flush()
        run = PipelineRunRecord(
            run_type="ingestion_parse",
            root_entity_type="source_document",
            root_entity_id=source.id,
        )
        self.session.add(run)
        self.session.flush()
        self.session.add(
            TaskNodeRecord(
                run_id=run.id,
                node_type="parse_source",
                input_hash=digest,
                idempotency_key=f"parse:{source.id}:v1",
                max_attempts=3,
            )
        )
        self.session.commit()
        return item, source, run

    def list_items(self) -> list[LibraryItemRecord]:
        return list(
            self.session.scalars(
                select(LibraryItemRecord).order_by(LibraryItemRecord.updated_at.desc())
            )
        )

    def get_item(self, item_id: str) -> LibraryItemRecord:
        item = self.session.scalar(
            select(LibraryItemRecord)
            .where(LibraryItemRecord.id == item_id)
            .options(selectinload(LibraryItemRecord.sources))
        )
        if item is None:
            raise LookupError("资料不存在")
        return item


def _source_type(filename: str, mime_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown"} or mime_type == "text/markdown":
        return "markdown"
    if suffix in {".html", ".htm"} or mime_type == "text/html":
        return "html"
    return "txt"
