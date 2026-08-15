from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LibraryItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    author: str | None
    content_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class SourceDocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    library_item_id: str
    source_type: str
    original_filename: str | None
    mime_type: str
    content_hash: str
    encoding: str | None
    parse_status: str


class LibraryItemDetail(LibraryItemView):
    sources: list[SourceDocumentView]


class ImportResponse(BaseModel):
    item: LibraryItemView
    source: SourceDocumentView
    run_id: str


ContentType = Literal["novel", "technical", "article", "unknown"]
