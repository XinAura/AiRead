from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from airead.core.database import SessionFactory
from airead.modules.models import AudioRenderRecord, EditionRecord


def main() -> None:
    parser = argparse.ArgumentParser(description="查看资料的音频任务状态")
    parser.add_argument("library_item_id")
    args = parser.parse_args()

    with SessionFactory() as session:
        renders = session.scalars(
            select(AudioRenderRecord)
            .join(EditionRecord, EditionRecord.id == AudioRenderRecord.edition_id)
            .where(EditionRecord.library_item_id == args.library_item_id)
            .options(selectinload(AudioRenderRecord.parts))
            .order_by(AudioRenderRecord.created_at)
        ).all()

        if not renders:
            print("没有音频任务")
            return

        for render in renders:
            counts = Counter(part.status for part in render.parts)
            status_summary = ", ".join(
                f"{status}={counts.get(status, 0)}"
                for status in ("succeeded", "running", "pending", "failed", "canceled")
            )
            print(
                f"render={render.id} edition={render.edition_id} status={render.status} "
                f"provider={render.provider} created_at={render.created_at.isoformat()}"
            )
            print(
                f"  parts={len(render.parts)} {status_summary} "
                f"batches={render.batch_count} next_batch={render.next_batch_index} "
                f"batch_size={render.batch_size}"
            )


if __name__ == "__main__":
    main()
