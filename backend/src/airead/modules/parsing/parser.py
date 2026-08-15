from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any

from bs4 import BeautifulSoup, Tag
from charset_normalizer import from_bytes

PARSER_VERSION = "phase1-v3"
CHINESE_NUMBER = r"[0-9一二三四五六七八九十百千万零〇两]+"
CHAPTER_PATTERN = re.compile(
    rf"^(?:(第{CHINESE_NUMBER}[章节卷部篇回集])|(?:chapter|part|volume)\s+[\divxlcdm]+)(?:[\s:：、.-]+.*)?$",
    re.IGNORECASE,
)
VOLUME_PATTERN = re.compile(
    rf"^(?:第{CHINESE_NUMBER}[集卷部篇]|(?:part|volume)\s+[\divxlcdm]+)",
    re.IGNORECASE,
)
COMPOUND_CHAPTER_PATTERN = re.compile(
    rf"^(?P<volume>第{CHINESE_NUMBER}[集卷部篇])\s+"
    rf"(?P<volume_title>.+?)\s+"
    rf"(?P<chapter>第{CHINESE_NUMBER}[章节回])"
    r"(?:[\s:：、.-]+(?P<chapter_title>.*))?$",
    re.IGNORECASE,
)
COMPOUND_PROLOGUE_PATTERN = re.compile(
    rf"^(?P<volume>第{CHINESE_NUMBER}[集卷部篇])\s+"
    r"(?P<volume_title>.+?)\s+"
    r"(?P<chapter>(?:引子|序章|楔子|序言|前言)(?:\s+.*)?)$",
    re.IGNORECASE,
)
AD_PATTERN = re.compile(
    r"(?:关注公众号|最新网址|本书来自|手机用户请|加入书签|求收藏|广告)", re.IGNORECASE
)


@dataclass
class ParsedBlock:
    block_type: str
    text: str
    source_start: int | None = None
    source_end: int | None = None
    parent_position: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    text: str
    encoding: str
    blocks: list[ParsedBlock]
    warnings: list[str] = field(default_factory=list)


def parse_source(payload: bytes, source_type: str, document_type: str) -> ParseResult:
    text, encoding = decode_payload(payload)
    cleaned = normalize_text(text)
    if source_type == "html":
        blocks = parse_html(cleaned)
    elif source_type == "markdown":
        blocks = parse_markdown(cleaned)
    else:
        blocks = parse_plain_text(cleaned)
    if document_type == "novel":
        blocks = enrich_novel_blocks(blocks)
    elif document_type in {"technical", "article"}:
        blocks = enrich_technical_blocks(blocks)
    return ParseResult(text=cleaned, encoding=encoding, blocks=blocks)


def decode_payload(payload: bytes) -> tuple[str, str]:
    if payload.startswith(b"\xef\xbb\xbf"):
        return payload.decode("utf-8-sig"), "utf-8-sig"
    best = from_bytes(payload).best()
    if best is None:
        raise ValueError("无法识别文件编码")
    return str(best), best.encoding or "unknown"


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufeff", "").replace("\u200b", "")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def parse_plain_text(text: str) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    offset = 0
    paragraph_lines: list[tuple[str, int]] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        value = "\n".join(line for line, _ in paragraph_lines).strip()
        start = paragraph_lines[0][1]
        blocks.append(
            ParsedBlock(
                "paragraph",
                value,
                start,
                start + len(value),
                metadata={"ad_candidate": bool(AD_PATTERN.search(value))},
            )
        )
        paragraph_lines.clear()

    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        line_start = offset + len(line) - len(line.lstrip())
        offset += len(raw_line)
        if not stripped:
            flush_paragraph()
            continue
        if CHAPTER_PATTERN.match(stripped):
            flush_paragraph()
            blocks.append(
                ParsedBlock(
                    "heading",
                    stripped,
                    line_start,
                    line_start + len(stripped),
                    metadata={"ad_candidate": False},
                )
            )
            continue
        paragraph_lines.append((stripped, line_start))
    flush_paragraph()
    return blocks


def parse_markdown(text: str) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    lines = text.splitlines(keepends=True)
    offset = 0
    paragraph: list[tuple[str, int]] = []
    in_code = False
    code_lines: list[str] = []
    code_start = 0
    code_language = ""

    def flush_paragraph() -> None:
        if not paragraph:
            return
        value = "".join(line for line, _ in paragraph).strip()
        start = paragraph[0][1]
        blocks.append(ParsedBlock("paragraph", value, start, start + len(value)))
        paragraph.clear()

    for raw in lines:
        line = raw.rstrip("\r\n")
        line_start = offset
        offset += len(raw)
        fence = re.match(r"^```\s*([\w.+#-]*)", line)
        if fence:
            if in_code:
                value = "\n".join(code_lines)
                blocks.append(
                    ParsedBlock(
                        "code",
                        value,
                        code_start,
                        line_start,
                        metadata={"language": code_language or "text"},
                    )
                )
                code_lines.clear()
                in_code = False
            else:
                flush_paragraph()
                in_code = True
                code_start = offset
                code_language = fence.group(1)
            continue
        if in_code:
            code_lines.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        image = re.match(r"^!\[([^]]*)]\(([^)]+)\)\s*$", line)
        if heading:
            flush_paragraph()
            blocks.append(
                ParsedBlock(
                    "heading",
                    heading.group(2).strip(),
                    line_start,
                    line_start + len(line),
                    metadata={"level": len(heading.group(1))},
                )
            )
        elif image:
            flush_paragraph()
            blocks.append(
                ParsedBlock(
                    "image",
                    image.group(1).strip(),
                    line_start,
                    line_start + len(line),
                    metadata={"src": image.group(2).strip()},
                )
            )
        elif not line.strip():
            flush_paragraph()
        else:
            paragraph.append((raw, line_start))
    flush_paragraph()
    if in_code:
        value = "\n".join(code_lines)
        blocks.append(
            ParsedBlock(
                "code", value, code_start, len(text), metadata={"language": code_language or "text"}
            )
        )
    return blocks


def parse_html(text: str) -> list[ParsedBlock]:
    soup = BeautifulSoup(text, "html.parser")
    root = soup.find("article") or soup.find("main") or soup.body or soup
    blocks: list[ParsedBlock] = []
    position = 0
    for node in root.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "img", "table", "ul", "ol"], recursive=True
    ):
        if not isinstance(node, Tag) or node.find_parent(["pre", "table", "ul", "ol"]) is not None:
            continue
        raw = str(node)
        found_at = text.find(raw, position)
        start: int | None
        if found_at >= 0:
            start = found_at
            position = found_at + len(raw)
        else:
            start = None
        end = start + len(raw) if start is not None else None
        if node.name.startswith("h"):
            blocks.append(
                ParsedBlock(
                    "heading",
                    node.get_text(" ", strip=True),
                    start,
                    end,
                    metadata={"level": int(node.name[1])},
                )
            )
        elif node.name == "pre":
            code = node.find("code")
            class_value = code.get("class") if code else None
            classes: list[str]
            if isinstance(class_value, list):
                classes = [str(item) for item in class_value]
            elif isinstance(class_value, str):
                classes = class_value.split()
            else:
                classes = []
            language = next(
                (
                    item.removeprefix("language-")
                    for item in classes
                    if item.startswith("language-")
                ),
                "text",
            )
            blocks.append(
                ParsedBlock(
                    "code",
                    node.get_text("\n", strip=True),
                    start,
                    end,
                    metadata={"language": language},
                )
            )
        elif node.name == "img":
            blocks.append(
                ParsedBlock(
                    "image",
                    unescape(str(node.get("alt", ""))).strip(),
                    start,
                    end,
                    metadata={"src": node.get("src", ""), "title": node.get("title")},
                )
            )
        elif node.name == "table":
            rows = [
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                for row in node.find_all("tr")
            ]
            blocks.append(
                ParsedBlock(
                    "table",
                    "\n".join(" | ".join(row) for row in rows),
                    start,
                    end,
                    metadata={"rows": rows},
                )
            )
        elif node.name in {"ul", "ol"}:
            items = [
                item.get_text(" ", strip=True) for item in node.find_all("li", recursive=False)
            ]
            blocks.append(
                ParsedBlock("list", "\n".join(items), start, end, metadata={"items": items})
            )
        else:
            value = node.get_text(" ", strip=True)
            if value:
                blocks.append(
                    ParsedBlock(
                        "paragraph",
                        value,
                        start,
                        end,
                        metadata={"ad_candidate": bool(AD_PATTERN.search(value))},
                    )
                )
    return blocks


def enrich_novel_blocks(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    enriched: list[ParsedBlock] = []
    current_volume: int | None = None
    current_chapter: int | None = None
    current_volume_key: str | None = None
    for block in blocks:
        if block.block_type == "heading" and CHAPTER_PATTERN.match(block.text):
            compound = split_compound_novel_title(block.text)
            if compound is not None:
                volume_key, volume_text, chapter_text = compound
                if volume_key != current_volume_key:
                    enriched.append(
                        ParsedBlock(
                            "volume",
                            volume_text,
                            block.source_start,
                            block.source_end,
                            metadata={
                                **block.metadata,
                                "compound_title": block.text,
                                "title_role": "volume",
                            },
                        )
                    )
                    current_volume = len(enriched) - 1
                    current_volume_key = volume_key
                if chapter_text is not None:
                    enriched.append(
                        ParsedBlock(
                            "chapter",
                            chapter_text,
                            block.source_start,
                            block.source_end,
                            parent_position=current_volume,
                            metadata={
                                **block.metadata,
                                "compound_title": block.text,
                                "title_role": "chapter",
                            },
                        )
                    )
                    current_chapter = len(enriched) - 1
                else:
                    current_chapter = None
                continue
            if VOLUME_PATTERN.match(block.text):
                block.block_type = "volume"
                block.parent_position = None
                enriched.append(block)
                current_volume = len(enriched) - 1
                current_volume_key = block.text
                current_chapter = None
            else:
                block.block_type = "chapter"
                block.parent_position = current_volume
                enriched.append(block)
                current_chapter = len(enriched) - 1
        elif current_chapter is not None:
            block.parent_position = current_chapter
            enriched.append(block)
        elif current_volume is not None:
            block.parent_position = current_volume
            enriched.append(block)
        else:
            enriched.append(block)
    return enriched


def split_compound_novel_title(title: str) -> tuple[str, str, str | None] | None:
    chapter_match = COMPOUND_CHAPTER_PATTERN.match(title)
    if chapter_match is not None:
        volume_key = chapter_match.group("volume")
        volume_text = f"{volume_key} {chapter_match.group('volume_title').strip()}"
        chapter = chapter_match.group("chapter")
        chapter_title = (chapter_match.group("chapter_title") or "").strip()
        chapter_text = f"{chapter} {chapter_title}".strip()
        return volume_key, volume_text, chapter_text

    prologue_match = COMPOUND_PROLOGUE_PATTERN.match(title)
    if prologue_match is not None:
        volume_key = prologue_match.group("volume")
        volume_text = f"{volume_key} {prologue_match.group('volume_title').strip()}"
        return volume_key, volume_text, prologue_match.group("chapter").strip()
    return None


def enrich_technical_blocks(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    current_heading: int | None = None
    for index, block in enumerate(blocks):
        if block.block_type == "heading":
            current_heading = index
            continue
        block.parent_position = current_heading
        if block.block_type == "image":
            label = f"{block.text} {block.metadata.get('src', '')}".lower()
            diagram_type = "image"
            for keyword, candidate in (
                ("flow", "flowchart"),
                ("流程", "flowchart"),
                ("usecase", "use_case"),
                ("用例", "use_case"),
                ("sequence", "sequence"),
                ("时序", "sequence"),
                ("class", "class"),
                ("类图", "class"),
                ("architecture", "architecture"),
                ("架构", "architecture"),
            ):
                if keyword in label:
                    diagram_type = candidate
                    break
            if diagram_type != "image":
                block.block_type = "diagram"
            block.metadata["diagram_type"] = diagram_type
    return blocks
