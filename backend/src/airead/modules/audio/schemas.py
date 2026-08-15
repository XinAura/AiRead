from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateAudioRequest(BaseModel):
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = Field(default="+0%", pattern=r"^[+-]\d+%$")
    pitch: str = Field(default="+0Hz", pattern=r"^[+-]\d+Hz$")


class AudioChunkView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    status: str
    attempt_count: int
    duration_ms: int | None
    error_code: str | None
    error_message: str | None


class AudioPartView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    batch_index: int
    title: str
    status: str
    duration_ms: int | None
    retry_count: int
    error_code: str | None
    error_message: str | None
    chunks: list[AudioChunkView]


class AudioRenderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    edition_id: str
    status: str
    voice: str
    rate: str
    pitch: str
    provider: str
    batch_size: int
    batch_count: int
    next_batch_index: int
    created_at: datetime
    parts: list[AudioPartView]


class CreateAudioResponse(BaseModel):
    render: AudioRenderView
    run_id: str
