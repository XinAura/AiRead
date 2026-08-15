from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from airead.core.database import SessionFactory
from airead.modules.models import PipelineRunRecord, utcnow


def main() -> None:
    parser = argparse.ArgumentParser(description="取消不再执行的流水线任务")
    parser.add_argument("run_id")
    args = parser.parse_args()

    with SessionFactory() as session:
        run = session.scalar(
            select(PipelineRunRecord)
            .where(PipelineRunRecord.id == args.run_id)
            .options(selectinload(PipelineRunRecord.nodes))
            .with_for_update()
        )
        if run is None:
            raise SystemExit("流水线任务不存在")
        if run.status in {"succeeded", "failed", "canceled"}:
            print(f"任务已处于终态: run={run.id} status={run.status}")
            return

        canceled_nodes = 0
        run.status = "canceled"
        for node in run.nodes:
            if node.status not in {"succeeded", "failed", "canceled"}:
                node.status = "canceled"
                node.finished_at = utcnow()
                canceled_nodes += 1
        session.commit()
        print(f"已取消 run={run.id}: nodes={canceled_nodes}")


if __name__ == "__main__":
    main()
