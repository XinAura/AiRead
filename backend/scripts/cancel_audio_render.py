from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from airead.core.database import SessionFactory
from airead.modules.models import (
    AudioPartRecord,
    AudioRenderRecord,
    PipelineRunRecord,
    utcnow,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="取消音频任务并保留成功产物")
    parser.add_argument("render_id")
    args = parser.parse_args()

    with SessionFactory() as session:
        render = session.scalar(
            select(AudioRenderRecord)
            .where(AudioRenderRecord.id == args.render_id)
            .options(selectinload(AudioRenderRecord.parts).selectinload(AudioPartRecord.chunks))
            .with_for_update()
        )
        if render is None:
            raise SystemExit("音频任务不存在")

        run = session.scalar(
            select(PipelineRunRecord)
            .where(
                PipelineRunRecord.root_entity_type == "audio_render",
                PipelineRunRecord.root_entity_id == render.id,
            )
            .options(selectinload(PipelineRunRecord.nodes))
        )

        canceled_parts = 0
        canceled_chunks = 0
        for part in render.parts:
            if part.status != "succeeded":
                part.status = "canceled"
                canceled_parts += 1
            for chunk in part.chunks:
                if chunk.status != "succeeded":
                    chunk.status = "canceled"
                    canceled_chunks += 1

        canceled_nodes = 0
        if run is not None:
            run.status = "canceled"
            for node in run.nodes:
                if node.status != "succeeded":
                    node.status = "canceled"
                    node.finished_at = utcnow()
                    canceled_nodes += 1

        render.status = "canceled"
        session.commit()
        print(
            f"已取消 render={render.id}: parts={canceled_parts}, "
            f"chunks={canceled_chunks}, nodes={canceled_nodes}"
        )


if __name__ == "__main__":
    main()
