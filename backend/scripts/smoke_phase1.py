import json
import time

import httpx

BASE_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 45


def wait_for_job(client: httpx.Client, run_id: str) -> dict[str, object]:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        payload = client.get(f"/jobs/{run_id}").raise_for_status().json()
        if payload["status"] in {"succeeded", "failed", "retryable"}:
            return payload
        time.sleep(0.25)
    raise TimeoutError(f"job {run_id} did not finish")


def main() -> None:
    sample = """第一卷 雪夜

第一章 出门

林冲离开家门，故事从这里开始。

关注公众号获取最新章节

第二章 转折

风雪越来越大，林冲作出了新的决定。
""".encode()
    with httpx.Client(base_url=BASE_URL, timeout=10) as client:
        imported = (
            client.post(
                "/library/items",
                data={"title": "阶段一联调小说", "author": "AiRead", "content_type": "novel"},
                files={"file": ("smoke-book.txt", sample, "text/plain")},
            )
            .raise_for_status()
            .json()
        )
        parse_job = wait_for_job(client, imported["run_id"])
        assert parse_job["status"] == "succeeded", parse_job

        source_id = imported["source"]["id"]
        documents = client.get(f"/sources/{source_id}/documents").raise_for_status().json()
        assert documents and documents[0]["status"] == "succeeded"
        blocks = client.get(f"/documents/{documents[0]['id']}/blocks").raise_for_status().json()
        assert [block["block_type"] for block in blocks].count("chapter") == 2

        item_id = imported["item"]["id"]
        editions = client.get(f"/library/items/{item_id}/editions").raise_for_status().json()
        assert editions and editions[0]["edition_type"] == "original_reading"
        assert len(editions[0]["blocks"]) == 2

        created_audio = (
            client.post(
                f"/editions/{editions[0]['id']}/audio",
                json={"voice": "mock-voice", "rate": "+0%", "pitch": "+0Hz"},
            )
            .raise_for_status()
            .json()
        )
        audio_job = wait_for_job(client, created_audio["run_id"])
        assert audio_job["status"] == "succeeded", audio_job
        render = (
            client.get(f"/audio-renders/{created_audio['render']['id']}").raise_for_status().json()
        )
        assert all(part["status"] == "succeeded" for part in render["parts"])

        stream = client.get(
            f"/audio-parts/{render['parts'][0]['id']}/stream",
            headers={"Range": "bytes=0-99"},
        )
        assert stream.status_code == 206
        assert stream.headers["content-range"].startswith("bytes 0-99/")
        assert len(stream.content) == 100

        print(
            json.dumps(
                {
                    "item_id": item_id,
                    "document_id": documents[0]["id"],
                    "edition_id": editions[0]["id"],
                    "audio_render_id": render["id"],
                    "parts": len(render["parts"]),
                    "range_status": stream.status_code,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
