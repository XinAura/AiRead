from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TaskNodeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_id: str | None
    node_type: str
    status: str
    progress: int
    attempt_count: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None


class PipelineRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_type: str
    root_entity_type: str
    root_entity_id: str
    status: str
    progress: int
    nodes: list[TaskNodeView]
    created_at: datetime
    updated_at: datetime
