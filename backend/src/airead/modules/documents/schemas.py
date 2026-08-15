from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ContentBlockView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parsed_document_id: str
    parent_id: str | None
    position: int
    block_type: str
    text: str
    source_start: int | None
    source_end: int | None
    block_metadata: dict[str, Any]


class ParsedDocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_document_id: str
    parser_version: str
    document_type: str
    language: str
    status: str
    created_at: datetime


class ParsedDocumentDetail(ParsedDocumentView):
    blocks: list[ContentBlockView]
