from airead.modules.parsing.parser import parse_source


def test_gbk_novel_keeps_offsets_and_builds_volume_chapter_tree() -> None:
    text = """第一卷 风雪

第一章 出门

林冲离开家门。

关注公众号领取全文

第二章 转折

故事继续。"""

    result = parse_source(text.encode("gbk"), "txt", "novel")

    assert result.encoding.lower() in {"gbk", "cp936", "gb18030"}
    assert [block.block_type for block in result.blocks] == [
        "volume",
        "chapter",
        "paragraph",
        "paragraph",
        "chapter",
        "paragraph",
    ]
    assert result.blocks[1].parent_position == 0
    assert result.blocks[2].parent_position == 1
    assert result.blocks[3].metadata["ad_candidate"] is True
    assert (
        result.text[result.blocks[2].source_start : result.blocks[2].source_end] == "林冲离开家门。"
    )


def test_novel_recognizes_chapters_without_blank_lines() -> None:
    text = "第一章 开始\n第一段正文。\n第二段正文。\n第二章 转折\n后续正文。"

    result = parse_source(text.encode(), "txt", "novel")

    assert [block.block_type for block in result.blocks] == [
        "chapter",
        "paragraph",
        "chapter",
        "paragraph",
    ]
    assert result.blocks[1].text == "第一段正文。\n第二段正文。"
    assert result.blocks[1].parent_position == 0
    assert result.blocks[3].parent_position == 2


def test_novel_splits_compound_volume_and_chapter_titles() -> None:
    text = """第一集 斗罗世界 引子 穿越的唐家三少
引子正文。
第一集 斗罗世界 第1章 斗罗大陆，异界唐三
第一章正文。
第一集 斗罗世界 第2章 废武魂与先天满魂力
第二章正文。
第二集 第一魂环 第8章 魂导器"""

    result = parse_source(text.encode(), "txt", "novel")

    assert [(block.block_type, block.text) for block in result.blocks] == [
        ("volume", "第一集 斗罗世界"),
        ("chapter", "引子 穿越的唐家三少"),
        ("paragraph", "引子正文。"),
        ("chapter", "第1章 斗罗大陆，异界唐三"),
        ("paragraph", "第一章正文。"),
        ("chapter", "第2章 废武魂与先天满魂力"),
        ("paragraph", "第二章正文。"),
        ("volume", "第二集 第一魂环"),
        ("chapter", "第8章 魂导器"),
    ]
    assert result.blocks[1].parent_position == 0
    assert result.blocks[3].parent_position == 0
    assert result.blocks[8].parent_position == 7


def test_markdown_technical_content_identifies_code_and_diagram() -> None:
    markdown = """# 请求处理

下面是入口代码。

```python
def handle(request):
    return request.id
```

![请求流程图](request-flow.png)
"""

    result = parse_source(markdown.encode(), "markdown", "technical")

    assert [block.block_type for block in result.blocks] == [
        "heading",
        "paragraph",
        "code",
        "diagram",
    ]
    assert result.blocks[2].metadata["language"] == "python"
    assert result.blocks[2].parent_position == 0
    assert result.blocks[3].metadata["diagram_type"] == "flowchart"


def test_html_technical_content_extracts_table_list_and_code() -> None:
    html = b"""<article><h1>Cache</h1><p>Intro</p>
    <pre><code class="language-java">return cache.get(key);</code></pre>
    <table><tr><th>Mode</th><th>Use</th></tr><tr><td>LRU</td><td>bounded</td></tr></table>
    <ul><li>fast</li><li>bounded</li></ul></article>"""

    result = parse_source(html, "html", "technical")

    assert [block.block_type for block in result.blocks] == [
        "heading",
        "paragraph",
        "code",
        "table",
        "list",
    ]
    assert result.blocks[2].metadata["language"] == "java"
    assert result.blocks[3].metadata["rows"][1] == ["LRU", "bounded"]
