from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from airead.core.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AssetRecord(Base, TimestampMixin):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class LibraryItemRecord(Base, TimestampMixin):
    __tablename__ = "library_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str | None] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    cover_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))

    sources: Mapped[list[SourceDocumentRecord]] = relationship(back_populates="library_item")


class SourceDocumentRecord(Base, TimestampMixin):
    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("library_item_id", "content_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    library_item_id: Mapped[str] = mapped_column(ForeignKey("library_items.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), nullable=False)
    cleaned_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    encoding: Mapped[str | None] = mapped_column(String(80))
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    library_item: Mapped[LibraryItemRecord] = relationship(back_populates="sources")
    parsed_documents: Mapped[list[ParsedDocumentRecord]] = relationship(back_populates="source")


class ParsedDocumentRecord(Base, TimestampMixin):
    __tablename__ = "parsed_documents"
    __table_args__ = (UniqueConstraint("source_document_id", "parser_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE")
    )
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    report_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))

    source: Mapped[SourceDocumentRecord] = relationship(back_populates="parsed_documents")
    blocks: Mapped[list[ContentBlockRecord]] = relationship(
        back_populates="document", order_by="ContentBlockRecord.position"
    )


class ContentBlockRecord(Base, TimestampMixin):
    __tablename__ = "content_blocks"
    __table_args__ = (UniqueConstraint("parsed_document_id", "position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    parsed_document_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_documents.id", ondelete="CASCADE")
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_blocks.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    source_start: Mapped[int | None] = mapped_column(Integer)
    source_end: Mapped[int | None] = mapped_column(Integer)
    block_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)

    document: Mapped[ParsedDocumentRecord] = relationship(back_populates="blocks")


class AgentRunRecord(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    library_item_id: Mapped[str] = mapped_column(ForeignKey("library_items.id", ondelete="CASCADE"))
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EvidenceRecord(Base, TimestampMixin):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    content_block_id: Mapped[str] = mapped_column(
        ForeignKey("content_blocks.id", ondelete="CASCADE")
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(40), nullable=False)
    inference: Mapped[bool] = mapped_column(default=False)


class EditionRecord(Base, TimestampMixin):
    __tablename__ = "editions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    library_item_id: Mapped[str] = mapped_column(ForeignKey("library_items.id", ondelete="CASCADE"))
    parsed_document_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_documents.id", ondelete="CASCADE")
    )
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"))
    edition_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    script_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_references: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")

    blocks: Mapped[list[EditionBlockRecord]] = relationship(
        back_populates="edition", order_by="EditionBlockRecord.position"
    )


class EditionBlockRecord(Base, TimestampMixin):
    __tablename__ = "edition_blocks"
    __table_args__ = (UniqueConstraint("edition_id", "position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    section_title: Mapped[str | None] = mapped_column(String(500))
    audio_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    edition: Mapped[EditionRecord] = relationship(back_populates="blocks")


class PipelineRunRecord(Base, TimestampMixin):
    __tablename__ = "pipeline_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    root_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    root_entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    nodes: Mapped[list[TaskNodeRecord]] = relationship(back_populates="run")


class TaskNodeRecord(Base, TimestampMixin):
    __tablename__ = "task_nodes"
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("task_nodes.id", ondelete="CASCADE"))
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    output_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[PipelineRunRecord] = relationship(back_populates="nodes")


class AudioRenderRecord(Base, TimestampMixin):
    __tablename__ = "audio_renders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    voice: Mapped[str] = mapped_column(String(120), nullable=False)
    rate: Mapped[str] = mapped_column(String(16), nullable=False, default="+0%")
    pitch: Mapped[str] = mapped_column(String(16), nullable=False, default="+0Hz")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    batch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    next_batch_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    parts: Mapped[list[AudioPartRecord]] = relationship(
        back_populates="render", order_by="AudioPartRecord.position"
    )


class AudioPartRecord(Base, TimestampMixin):
    __tablename__ = "audio_parts"
    __table_args__ = (UniqueConstraint("audio_render_id", "position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    audio_render_id: Mapped[str] = mapped_column(ForeignKey("audio_renders.id", ondelete="CASCADE"))
    edition_block_id: Mapped[str] = mapped_column(
        ForeignKey("edition_blocks.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    audio_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)

    render: Mapped[AudioRenderRecord] = relationship(back_populates="parts")
    chunks: Mapped[list[AudioChunkRecord]] = relationship(
        back_populates="part", order_by="AudioChunkRecord.position"
    )


class AudioChunkRecord(Base, TimestampMixin):
    __tablename__ = "audio_chunks"
    __table_args__ = (UniqueConstraint("audio_part_id", "position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    audio_part_id: Mapped[str] = mapped_column(ForeignKey("audio_parts.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_block_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    audio_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)

    part: Mapped[AudioPartRecord] = relationship(back_populates="chunks")


class TtsCacheRecord(Base, TimestampMixin):
    __tablename__ = "tts_cache"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    audio_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(40), nullable=False)
