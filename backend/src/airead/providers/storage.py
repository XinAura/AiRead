from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from minio import Minio

from airead.core.config import Settings, get_settings


@dataclass(frozen=True)
class StoredObject:
    key: str
    byte_size: int
    content_hash: str


class ObjectStorage(Protocol):
    def put(self, key: str, payload: bytes, content_type: str) -> StoredObject: ...

    def read(self, key: str) -> bytes: ...

    def local_path(self, key: str) -> Path | None: ...


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def put(self, key: str, payload: bytes, content_type: str) -> StoredObject:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
        return StoredObject(key=key, byte_size=len(payload), content_hash=_sha256(payload))

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("storage key escapes the configured root")
        return candidate


class MinioObjectStorage:
    def __init__(self, settings: Settings) -> None:
        endpoint = settings.s3_endpoint.removeprefix("http://").removeprefix("https://")
        self.client = Minio(
            endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=settings.s3_endpoint.startswith("https://"),
        )
        self.bucket = settings.s3_bucket
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put(self, key: str, payload: bytes, content_type: str) -> StoredObject:
        self.client.put_object(
            self.bucket,
            key,
            io.BytesIO(payload),
            len(payload),
            content_type=content_type,
        )
        return StoredObject(key=key, byte_size=len(payload), content_hash=_sha256(payload))

    def read(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def local_path(self, key: str) -> None:
        del key
        return None


def build_storage(settings: Settings | None = None) -> ObjectStorage:
    settings = settings or get_settings()
    if settings.storage_backend == "s3":
        return MinioObjectStorage(settings)
    return LocalObjectStorage(settings.storage_root)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
