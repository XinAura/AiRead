import pytest
from fastapi import HTTPException

from airead.api.main import _parse_range, app


def test_openapi_contains_phase_one_routes() -> None:
    paths = app.openapi()["paths"]
    assert "/library/items" in paths
    assert "/documents/{document_id}/blocks" in paths
    assert "/editions/{edition_id}/audio" in paths
    assert "/audio-parts/{part_id}/retry" in paths
    assert "/audio-parts/{part_id}/stream" in paths
    assert "/jobs/{run_id}" in paths


@pytest.mark.parametrize(
    ("header", "total", "expected"),
    [
        ("bytes=0-9", 100, (0, 9)),
        ("bytes=10-", 100, (10, 99)),
        ("bytes=-20", 100, (80, 99)),
        ("bytes=90-200", 100, (90, 99)),
    ],
)
def test_parse_http_range(header: str, total: int, expected: tuple[int, int]) -> None:
    assert _parse_range(header, total) == expected


def test_invalid_http_range_returns_416() -> None:
    with pytest.raises(HTTPException) as raised:
        _parse_range("bytes=100-120", 100)
    assert raised.value.status_code == 416
    assert raised.value.headers == {"Content-Range": "bytes */100"}
