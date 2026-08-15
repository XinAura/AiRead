from pydantic import BaseModel, ConfigDict


class EditionBlockView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    kind: str
    text: str
    source_block_ids: list[str]
    section_title: str | None
    audio_status: str


class EditionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    library_item_id: str
    parsed_document_id: str
    edition_type: str
    title: str
    full_text: str
    script_version: str
    status: str
    blocks: list[EditionBlockView]
