from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="AIREAD_",
        extra="ignore",
    )

    env: str = "development"
    database_url: str = "postgresql+psycopg://airead:airead_dev@127.0.0.1:5432/airead"
    redis_url: str = "redis://127.0.0.1:6379/0"
    storage_backend: Literal["local", "s3"] = "local"
    storage_root: Path = PROJECT_ROOT / "storage"
    s3_endpoint: str = "http://127.0.0.1:9000"
    s3_bucket: str = "airead"
    s3_access_key: str = "airead"
    s3_secret_key: str = "change-me-in-env"
    tts_provider: Literal["edge", "mock"] = "edge"
    tts_global_concurrency: int = Field(default=3, ge=1, le=20)
    tts_chunk_concurrency: int = Field(default=2, ge=1, le=10)
    audio_job_concurrency: int = Field(default=2, ge=1, le=10)
    audio_batch_size: int = Field(default=3, ge=1, le=20)
    assemble_concurrency: int = Field(default=1, ge=1, le=5)
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    cors_origins: list[str] = ["http://127.0.0.1:3000", "http://localhost:3000"]
    development_cors_origin_regex: str = (
        r"^http://(?:127\.0\.0\.1|localhost|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+):3000$"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
