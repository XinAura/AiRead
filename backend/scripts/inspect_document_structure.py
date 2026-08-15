from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from airead.core.database import SessionFactory
from airead.modules.models import ContentBlockRecord, EditionRecord, ParsedDocumentRecord


def main() -> None:
    parser = argparse.ArgumentParser(description="查看结构化文档的卷章和朗读分组")
    parser.add_argument("document_id")
    args = parser.parse_args()

    with SessionFactory() as session:
        document = session.get(ParsedDocumentRecord, args.document_id)
        if document is None:
            raise SystemExit("结构化文档不存在")

        blocks = list(
            session.scalars(
                select(ContentBlockRecord)
                .where(ContentBlockRecord.parsed_document_id == document.id)
                .order_by(ContentBlockRecord.position)
            )
        )
        counts = Counter(block.block_type for block in blocks)
        print(
            f"document={document.id} parser={document.parser_version} status={document.status} "
            f"blocks={len(blocks)} volumes={counts['volume']} chapters={counts['chapter']}"
        )
        for block in [
            candidate for candidate in blocks if candidate.block_type in {"volume", "chapter"}
        ][:10]:
            print(
                f"  block={block.position} type={block.block_type} "
                f"parent={block.parent_id or '-'} title={block.text}"
            )

        edition = session.scalar(
            select(EditionRecord)
            .where(EditionRecord.parsed_document_id == document.id)
            .options(selectinload(EditionRecord.blocks))
            .order_by(EditionRecord.created_at.desc())
        )
        if edition is None:
            print("edition=none")
            return
        print(f"edition={edition.id} script={edition.script_version} parts={len(edition.blocks)}")
        for block in edition.blocks[:5]:
            print(f"  part={block.position} title={block.section_title}")


if __name__ == "__main__":
    main()
