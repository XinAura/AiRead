from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from airead.modules.models import (
    ContentBlockRecord,
    EditionBlockRecord,
    EditionRecord,
    ParsedDocumentRecord,
)

SCRIPT_VERSION = "original-v2"


class EditionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_original(self, parsed_document_id: str) -> EditionRecord:
        existing = self.session.scalar(
            select(EditionRecord)
            .where(
                EditionRecord.parsed_document_id == parsed_document_id,
                EditionRecord.edition_type == "original_reading",
                EditionRecord.script_version == SCRIPT_VERSION,
            )
            .options(selectinload(EditionRecord.blocks))
        )
        if existing is not None:
            return existing
        document = self.session.scalar(
            select(ParsedDocumentRecord)
            .where(ParsedDocumentRecord.id == parsed_document_id)
            .options(
                selectinload(ParsedDocumentRecord.blocks), selectinload(ParsedDocumentRecord.source)
            )
        )
        if document is None or document.status != "succeeded":
            raise ValueError("结构化文档尚未完成")
        groups = _group_blocks(document.blocks, document.document_type)
        edition_blocks: list[EditionBlockRecord] = []
        for position, group in enumerate(groups):
            text = "\n\n".join(filter(None, (_to_reading_text(block) for block in group)))
            if not text.strip():
                continue
            title = _build_section_title(group, position)
            edition_blocks.append(
                EditionBlockRecord(
                    position=len(edition_blocks),
                    kind="original",
                    text=text,
                    source_block_ids=[block.id for block in group],
                    section_title=title,
                )
            )
        if not edition_blocks:
            raise ValueError("文档没有可朗读内容")
        item = document.source.library_item
        edition = EditionRecord(
            library_item_id=item.id,
            parsed_document_id=document.id,
            edition_type="original_reading",
            title=f"{item.title} - 原文朗读",
            full_text="\n\n".join(block.text for block in edition_blocks),
            script_version=SCRIPT_VERSION,
            source_references=[block.id for block in document.blocks],
            status="ready",
            blocks=edition_blocks,
        )
        self.session.add(edition)
        self.session.commit()
        self.session.refresh(edition)
        return edition

    def get(self, edition_id: str) -> EditionRecord:
        edition = self.session.scalar(
            select(EditionRecord)
            .where(EditionRecord.id == edition_id)
            .options(selectinload(EditionRecord.blocks))
        )
        if edition is None:
            raise LookupError("朗读版本不存在")
        return edition

    def list_for_item(self, item_id: str) -> list[EditionRecord]:
        return list(
            self.session.scalars(
                select(EditionRecord)
                .where(EditionRecord.library_item_id == item_id)
                .options(selectinload(EditionRecord.blocks))
                .order_by(EditionRecord.created_at.desc())
            )
        )


def _group_blocks(
    blocks: list[ContentBlockRecord], document_type: str
) -> list[list[ContentBlockRecord]]:
    if document_type == "novel":
        return _group_novel_blocks(blocks)
    roots = {"heading"}
    groups: list[list[ContentBlockRecord]] = []
    current: list[ContentBlockRecord] = []
    for block in blocks:
        if block.block_type in roots and current:
            groups.append(current)
            current = []
        current.append(block)
    if current:
        groups.append(current)
    return groups


def _group_novel_blocks(
    blocks: list[ContentBlockRecord],
) -> list[list[ContentBlockRecord]]:
    groups: list[list[ContentBlockRecord]] = []
    current: list[ContentBlockRecord] = []
    volume_prefix: list[ContentBlockRecord] = []
    started_chapters = False
    for block in blocks:
        if block.block_type == "volume":
            if current and started_chapters:
                groups.append(current)
                current = []
            elif current:
                volume_prefix.extend(current)
                current = []
            volume_prefix.append(block)
        elif block.block_type == "chapter":
            if current and started_chapters:
                groups.append(current)
            elif current:
                volume_prefix.extend(current)
            current = [*volume_prefix, block]
            volume_prefix = []
            started_chapters = True
        else:
            if started_chapters and not current and volume_prefix:
                current = volume_prefix
                volume_prefix = []
            current.append(block)
    if current:
        groups.append(current)
    elif volume_prefix:
        groups.append(volume_prefix)
    return groups


def _build_section_title(group: list[ContentBlockRecord], position: int) -> str:
    volume = next((block.text for block in group if block.block_type == "volume"), None)
    chapter = next((block.text for block in group if block.block_type == "chapter"), None)
    if volume and chapter:
        return f"{volume} · {chapter}"
    return (
        chapter
        or volume
        or next(
            (block.text for block in group if block.block_type == "heading"),
            f"第 {position + 1} 部分",
        )
    )


def _to_reading_text(block: ContentBlockRecord) -> str:
    if block.block_metadata.get("ad_candidate"):
        return ""
    if block.block_type == "code":
        language = block.block_metadata.get("language", "文本")
        line_count = len(block.text.splitlines())
        return f"此处为 {language} 代码块，共 {line_count} 行。\n{block.text}"
    if block.block_type in {"image", "diagram"}:
        kind = block.block_metadata.get("diagram_type", "image")
        alt = block.text or "没有替代文字"
        return f"此处包含一张 {kind}，图片说明：{alt}。"
    if block.block_type == "table":
        return f"以下是一张表格。\n{block.text}"
    return block.text
