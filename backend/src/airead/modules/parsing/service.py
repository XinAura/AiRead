from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from airead.modules.models import (
    AssetRecord,
    ContentBlockRecord,
    ParsedDocumentRecord,
    PipelineRunRecord,
    SourceDocumentRecord,
    TaskNodeRecord,
    utcnow,
)
from airead.modules.parsing.parser import PARSER_VERSION, parse_source
from airead.providers.storage import ObjectStorage


class ParsingService:
    def __init__(self, session: Session, storage: ObjectStorage) -> None:
        self.session = session
        self.storage = storage

    def parse(self, source_id: str, run_id: str) -> ParsedDocumentRecord:
        source = self.session.get(SourceDocumentRecord, source_id)
        run = self.session.get(PipelineRunRecord, run_id)
        node = self.session.scalar(select(TaskNodeRecord).where(TaskNodeRecord.run_id == run_id))
        if source is None or run is None or node is None:
            raise LookupError("解析任务不存在")
        existing = self.session.scalar(
            select(ParsedDocumentRecord).where(
                ParsedDocumentRecord.source_document_id == source_id,
                ParsedDocumentRecord.parser_version == PARSER_VERSION,
                ParsedDocumentRecord.status == "succeeded",
            )
        )
        if existing is not None:
            node.status = "succeeded"
            node.progress = 100
            run.status = "succeeded"
            run.progress = 100
            self.session.commit()
            return existing

        node.status = "running"
        node.attempt_count += 1
        node.started_at = node.started_at or utcnow()
        node.heartbeat_at = utcnow()
        run.status = "running"
        run.progress = 10
        source.parse_status = "running"
        self.session.commit()
        asset = self.session.get(AssetRecord, source.asset_id)
        if asset is None:
            raise LookupError("原始文件资源不存在")

        try:
            result = parse_source(
                self.storage.read(asset.storage_key),
                source.source_type,
                source.library_item.content_type,
            )
            cleaned_bytes = result.text.encode("utf-8")
            cleaned_key = (
                f"cleaned/{source.id}/{hashlib.sha256(cleaned_bytes).hexdigest()[:16]}.txt"
            )
            stored = self.storage.put(cleaned_key, cleaned_bytes, "text/plain; charset=utf-8")
            cleaned_asset = self._reuse_or_create_asset(
                kind="cleaned_text",
                storage_key=stored.key,
                mime_type="text/plain; charset=utf-8",
                byte_size=stored.byte_size,
                content_hash=stored.content_hash,
            )
            source.cleaned_asset_id = cleaned_asset.id
            source.encoding = result.encoding

            document = self.session.scalar(
                select(ParsedDocumentRecord).where(
                    ParsedDocumentRecord.source_document_id == source.id,
                    ParsedDocumentRecord.parser_version == PARSER_VERSION,
                )
            )
            if document is None:
                document = ParsedDocumentRecord(
                    source_document_id=source.id,
                    parser_version=PARSER_VERSION,
                    document_type=source.library_item.content_type,
                    status="running",
                )
                self.session.add(document)
                self.session.flush()
            else:
                self.session.execute(
                    delete(ContentBlockRecord).where(
                        ContentBlockRecord.parsed_document_id == document.id
                    )
                )
                self.session.flush()

            records: list[ContentBlockRecord] = []
            for position, block in enumerate(result.blocks):
                record = ContentBlockRecord(
                    id=str(
                        uuid.uuid5(
                            uuid.UUID(document.id),
                            f"{position}:{block.block_type}:{block.source_start}",
                        )
                    ),
                    parsed_document_id=document.id,
                    position=position,
                    block_type=block.block_type,
                    text=block.text,
                    source_start=block.source_start,
                    source_end=block.source_end,
                    block_metadata=block.metadata,
                    parser_version=PARSER_VERSION,
                )
                records.append(record)
                self.session.add(record)
            self.session.flush()
            for position, block in enumerate(result.blocks):
                if block.parent_position is not None:
                    records[position].parent_id = records[block.parent_position].id

            report = json.dumps(
                {
                    "parser_version": PARSER_VERSION,
                    "encoding": result.encoding,
                    "warnings": result.warnings,
                    "block_count": len(records),
                },
                ensure_ascii=False,
            ).encode()
            report_key = f"parse-reports/{document.id}.json"
            report_stored = self.storage.put(report_key, report, "application/json")
            report_asset = self._reuse_or_create_asset(
                kind="parse_report",
                storage_key=report_stored.key,
                mime_type="application/json",
                byte_size=report_stored.byte_size,
                content_hash=report_stored.content_hash,
            )
            document.report_asset_id = report_asset.id
            document.status = "succeeded"
            source.parse_status = "succeeded"
            node.status = "succeeded"
            node.progress = 100
            node.finished_at = utcnow()
            run.status = "succeeded"
            run.progress = 100
            self.session.commit()
            return document
        except Exception as exc:
            self.session.rollback()
            failed_source = self.session.get(SourceDocumentRecord, source_id)
            failed_run = self.session.get(PipelineRunRecord, run_id)
            failed_node = self.session.scalar(
                select(TaskNodeRecord).where(TaskNodeRecord.run_id == run_id)
            )
            if failed_source is not None:
                failed_source.parse_status = "failed"
            if failed_node is not None:
                failed_node.status = (
                    "retryable"
                    if failed_node.attempt_count < failed_node.max_attempts
                    else "failed"
                )
                failed_node.error_code = "parse_failed"
                failed_node.error_message = str(exc)[:2000]
                failed_node.finished_at = utcnow()
            if failed_run is not None and failed_node is not None:
                failed_run.status = failed_node.status
            self.session.commit()
            raise

    def _reuse_or_create_asset(
        self,
        *,
        kind: str,
        storage_key: str,
        mime_type: str,
        byte_size: int,
        content_hash: str,
    ) -> AssetRecord:
        asset = self.session.scalar(
            select(AssetRecord).where(AssetRecord.storage_key == storage_key)
        )
        if asset is None:
            asset = AssetRecord(
                kind=kind,
                storage_key=storage_key,
                mime_type=mime_type,
                byte_size=byte_size,
                content_hash=content_hash,
            )
            self.session.add(asset)
            self.session.flush()
        return asset
