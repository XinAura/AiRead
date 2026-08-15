from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from airead.modules.editions.service import EditionService
from airead.modules.library.service import LibraryService
from airead.modules.models import (
    AssetRecord,
    ContentBlockRecord,
    ParsedDocumentRecord,
    PipelineRunRecord,
    TaskNodeRecord,
)
from airead.modules.parsing import service as parsing_service_module
from airead.modules.parsing.service import ParsingService
from airead.providers.storage import LocalObjectStorage


def test_import_parse_and_original_edition_are_idempotent(session: Session, tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path)
    item, source, run = LibraryService(session, storage).import_file(
        title="测试小说",
        author="作者",
        content_type="novel",
        filename="book.txt",
        mime_type="text/plain",
        payload=(
            "测试小说\n\n第一卷 风雪\n\n第一章 开始\n\n正文。\n\n第二章 继续\n\n后续。"
        ).encode(),
    )

    document = ParsingService(session, storage).parse(source.id, run.id)
    edition = EditionService(session).create_original(document.id)
    repeated_document = ParsingService(session, storage).parse(source.id, run.id)
    repeated_edition = EditionService(session).create_original(document.id)

    assert item.id == edition.library_item_id
    assert repeated_document.id == document.id
    assert repeated_edition.id == edition.id
    assert [block.section_title for block in edition.blocks] == [
        "第一卷 风雪 · 第一章 开始",
        "第二章 继续",
    ]
    assert edition.blocks[0].source_block_ids
    assert session.scalar(select(func.count()).select_from(ParsedDocumentRecord)) == 1
    assert session.scalar(select(func.count()).select_from(ContentBlockRecord)) == 6


def test_original_edition_marks_non_text_blocks_for_listening(
    session: Session, tmp_path: Path
) -> None:
    storage = LocalObjectStorage(tmp_path)
    _, source, run = LibraryService(session, storage).import_file(
        title="技术文章",
        author=None,
        content_type="technical",
        filename="article.md",
        mime_type="text/markdown",
        payload=b"# API\n\n```python\nprint('ok')\n```\n\n![flow](flow.png)",
    )

    document = ParsingService(session, storage).parse(source.id, run.id)
    edition = EditionService(session).create_original(document.id)

    assert "python 代码块" in edition.full_text
    assert "flowchart" in edition.full_text
    assert set(edition.source_references) == {block.id for block in document.blocks}


def test_new_parser_version_reuses_cleaned_asset(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalObjectStorage(tmp_path)
    _, source, first_run = LibraryService(session, storage).import_file(
        title="无空行小说",
        author=None,
        content_type="novel",
        filename="book.txt",
        mime_type="text/plain",
        payload="第一集 开始\n正文。\n第二集 继续\n后续。".encode(),
    )
    first_document = ParsingService(session, storage).parse(source.id, first_run.id)
    monkeypatch.setattr(parsing_service_module, "PARSER_VERSION", "phase1-v-next")
    second_run = PipelineRunRecord(
        run_type="ingestion_parse",
        root_entity_type="source_document",
        root_entity_id=source.id,
    )
    session.add(second_run)
    session.flush()
    session.add(
        TaskNodeRecord(
            run_id=second_run.id,
            node_type="parse_source",
            input_hash=source.content_hash,
            idempotency_key=f"parse:{source.id}:phase1-v-next",
        )
    )
    session.commit()

    second_document = ParsingService(session, storage).parse(source.id, second_run.id)

    assert second_document.id != first_document.id
    assert session.scalar(select(func.count()).select_from(ParsedDocumentRecord)) == 2
    assert (
        session.scalar(
            select(func.count()).select_from(AssetRecord).where(AssetRecord.kind == "cleaned_text")
        )
        == 1
    )
