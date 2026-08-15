"use client";

import type { paths } from "@airead/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  AudioLines,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronsDown,
  ChevronsUp,
  CircleAlert,
  Code2,
  FileText,
  FileImage,
  Headphones,
  LoaderCircle,
  RefreshCw,
  Table2,
} from "lucide-react";
import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";

import { api, audioStreamUrl } from "@/lib/api";

type Item =
  paths["/library/items/{item_id}"]["get"]["responses"]["200"]["content"]["application/json"];
type Documents =
  paths["/sources/{source_id}/documents"]["get"]["responses"]["200"]["content"]["application/json"];
type Blocks =
  paths["/documents/{document_id}/blocks"]["get"]["responses"]["200"]["content"]["application/json"];
type Editions =
  paths["/library/items/{item_id}/editions"]["get"]["responses"]["200"]["content"]["application/json"];
type AudioRenders =
  paths["/editions/{edition_id}/audio-renders"]["get"]["responses"]["200"]["content"]["application/json"];
type CreateAudio =
  paths["/editions/{edition_id}/audio"]["post"]["responses"]["202"]["content"]["application/json"];

const blockIcons: Record<string, typeof BookOpen> = {
  code: Code2,
  image: FileImage,
  diagram: FileImage,
  table: Table2,
};

type ContentBlock = Blocks[number];
type DocumentSection = {
  id: string;
  anchorIds: string[];
  title: string;
  blocks: ContentBlock[];
};

export default function LibraryDetailPage({
  params,
}: {
  params: Promise<{ itemId: string }>;
}) {
  const { itemId } = use(params);
  const queryClient = useQueryClient();
  const [voice, setVoice] = useState("zh-CN-XiaoxiaoNeural");
  const [mobileView, setMobileView] = useState<"content" | "audio">("content");
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(),
  );
  const item = useQuery({
    queryKey: ["item", itemId],
    queryFn: () => api<Item>(`/library/items/${itemId}`),
    refetchInterval: (query) =>
      query.state.data?.sources.some((entry) =>
        ["pending", "running"].includes(entry.parse_status),
      )
        ? 2_000
        : false,
  });
  const source = item.data?.sources[0];
  const documents = useQuery({
    queryKey: ["documents", source?.id],
    queryFn: () => api<Documents>(`/sources/${source!.id}/documents`),
    enabled: Boolean(source),
    refetchInterval: source?.parse_status === "succeeded" ? false : 2_000,
  });
  const document = documents.data?.[0];
  const blocks = useQuery({
    queryKey: ["blocks", document?.id],
    queryFn: () => api<Blocks>(`/documents/${document!.id}/blocks`),
    enabled: document?.status === "succeeded",
  });
  const editions = useQuery({
    queryKey: ["editions", itemId],
    queryFn: () => api<Editions>(`/library/items/${itemId}/editions`),
    refetchInterval: (query) =>
      source?.parse_status === "succeeded" && !query.state.data?.length
        ? 1_000
        : false,
  });
  const edition = editions.data?.[0];
  const renders = useQuery({
    queryKey: ["audio-renders", edition?.id],
    queryFn: () => api<AudioRenders>(`/editions/${edition!.id}/audio-renders`),
    enabled: Boolean(edition),
    refetchInterval: (query) => {
      const current = query.state.data?.[0];
      return current && ["pending", "running"].includes(current.status)
        ? 2_000
        : false;
    },
  });
  const currentRender = renders.data?.[0];
  const activeBatchIndex = currentRender
    ? Math.min(
        currentRender.next_batch_index - 1,
        currentRender.batch_count - 1,
      )
    : 0;
  const visibleParts = currentRender?.parts.filter(
    (part) => part.status !== "pending" || part.batch_index <= activeBatchIndex,
  );
  const createAudio = useMutation({
    mutationFn: () =>
      api<CreateAudio>(`/editions/${edition!.id}/audio`, {
        method: "POST",
        body: JSON.stringify({ voice, rate: "+0%", pitch: "+0Hz" }),
      }),
    onSuccess: async () => {
      setMobileView("audio");
      await queryClient.invalidateQueries({
        queryKey: ["audio-renders", edition?.id],
      });
    },
  });
  const retryPart = useMutation({
    mutationFn: (partId: string) =>
      api(`/audio-parts/${partId}/retry`, { method: "POST" }),
    onSuccess: async () =>
      queryClient.invalidateQueries({
        queryKey: ["audio-renders", edition?.id],
      }),
  });
  const chapters = useMemo(
    () =>
      blocks.data?.filter((block) =>
        ["volume", "chapter", "heading"].includes(block.block_type),
      ) ?? [],
    [blocks.data],
  );
  const sections = useMemo(
    () => groupDocumentBlocks(blocks.data ?? []),
    [blocks.data],
  );

  useEffect(() => {
    const firstSection = sections[0];
    setExpandedSections(firstSection ? new Set([firstSection.id]) : new Set());
  }, [document?.id, sections]);

  const toggleSection = (sectionId: string) => {
    setExpandedSections((current) => {
      const next = new Set(current);
      if (next.has(sectionId)) next.delete(sectionId);
      else next.add(sectionId);
      return next;
    });
  };

  if (item.isLoading)
    return (
      <div className="page-loading">
        <LoaderCircle className="spin" />
        正在加载资料…
      </div>
    );
  if (!item.data)
    return (
      <div className="workspace">
        <div className="error-banner">资料不存在或后端暂时不可用。</div>
      </div>
    );

  return (
    <div className="detail-workspace">
      <header className="detail-header">
        <Link className="back-link" href="/library">
          <ArrowLeft size={16} />
          返回资料库
        </Link>
        <div className="title-line">
          <div>
            <p className="eyebrow">
              {item.data.content_type === "novel" ? "小说" : "技术资料"}
            </p>
            <h1>{item.data.title}</h1>
            <p className="subtle">{item.data.author || "作者未填写"}</p>
          </div>
          <span className={`parse-badge ${source?.parse_status ?? "pending"}`}>
            {source?.parse_status === "succeeded" ? (
              <Check size={15} />
            ) : (
              <LoaderCircle className="spin" size={15} />
            )}
            {source?.parse_status === "succeeded"
              ? "解析完成"
              : source?.parse_status === "failed"
                ? "解析失败"
                : "后台解析中"}
          </span>
        </div>
      </header>

      <div className="mobile-view-switch" role="tablist" aria-label="资料视图">
        <button
          role="tab"
          aria-selected={mobileView === "content"}
          className={mobileView === "content" ? "active" : ""}
          onClick={() => setMobileView("content")}
        >
          <FileText size={16} />
          原文
        </button>
        <button
          role="tab"
          aria-selected={mobileView === "audio"}
          className={mobileView === "audio" ? "active" : ""}
          onClick={() => setMobileView("audio")}
        >
          <Headphones size={16} />
          音频
          {currentRender ? (
            <span>
              {
                currentRender.parts.filter(
                  (part) => part.status === "succeeded",
                ).length
              }
            </span>
          ) : null}
        </button>
      </div>

      <div className={`reader-grid mobile-view-${mobileView}`}>
        <aside className="outline-panel">
          <div className="panel-title">
            <span>内容结构</span>
            <small>{chapters.length} 个节点</small>
          </div>
          <nav className="chapter-list">
            {chapters.length ? (
              chapters.map((chapter, index) => (
                <a
                  href={`#block-${chapter.id}`}
                  key={chapter.id}
                  className={
                    chapter.block_type === "volume" ? "volume-link" : ""
                  }
                  onClick={() => setMobileView("content")}
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  {chapter.text}
                  <ChevronRight size={14} />
                </a>
              ))
            ) : (
              <p className="panel-placeholder">解析完成后显示章节与标题。</p>
            )}
          </nav>
        </aside>

        <section className="document-panel">
          <div className="panel-title document-panel-title">
            <div>
              <span>结构化原文</span>
              <small>{blocks.data?.length ?? 0} 个内容块</small>
            </div>
            {sections.length ? (
              <div className="document-actions">
                <button
                  title="展开全部章节"
                  onClick={() =>
                    setExpandedSections(
                      new Set(sections.map((section) => section.id)),
                    )
                  }
                >
                  <ChevronsDown size={14} />
                  展开全部
                </button>
                <button
                  title="收起全部章节"
                  onClick={() => setExpandedSections(new Set())}
                >
                  <ChevronsUp size={14} />
                  收起全部
                </button>
              </div>
            ) : null}
          </div>
          <div className="document-flow">
            {!blocks.data ? (
              <div className="processing-state">
                <LoaderCircle className="spin" />
                <strong>正在建立事实层</strong>
                <p>系统正在检测编码、规划章节并识别代码和图表。</p>
              </div>
            ) : null}
            {sections.map((section) => {
              const expanded = expandedSections.has(section.id);
              return (
                <section
                  className="document-section"
                  id={`block-${section.id}`}
                  key={section.id}
                >
                  {section.anchorIds
                    .filter((anchorId) => anchorId !== section.id)
                    .map((anchorId) => (
                      <span
                        aria-hidden="true"
                        className="section-anchor"
                        id={`block-${anchorId}`}
                        key={anchorId}
                      />
                    ))}
                  <button
                    className="section-toggle"
                    aria-expanded={expanded}
                    onClick={() => toggleSection(section.id)}
                  >
                    <span>
                      <ChevronDown
                        className={expanded ? "expanded" : ""}
                        size={17}
                      />
                      {section.title}
                    </span>
                    <small>{section.blocks.length} 个内容块</small>
                  </button>
                  {expanded ? (
                    <div className="section-content">
                      {section.blocks.map((block) => renderContentBlock(block))}
                    </div>
                  ) : null}
                </section>
              );
            })}
          </div>
        </section>

        <aside className="production-panel">
          <div className="panel-title">
            <span>原文朗读</span>
            <AudioLines size={17} />
          </div>
          {!edition ? (
            <div className="panel-placeholder">
              <LoaderCircle className="spin" size={18} />
              <p>结构化完成后自动创建原文朗读版。</p>
            </div>
          ) : (
            <>
              <div className="edition-summary">
                <span className="edition-icon">
                  <BookOpen size={18} />
                </span>
                <div>
                  <strong>{edition.title}</strong>
                  <small>
                    {edition.blocks.length} 个可播放章节 · 原文可追溯
                  </small>
                </div>
              </div>
              {currentRender?.provider === "mock" ? (
                <div className="provider-warning">
                  <CircleAlert size={16} />
                  <div>
                    <strong>这是测试音频</strong>
                    <small>嘀声来自 Mock TTS，请重新生成 Edge 人声。</small>
                  </div>
                </div>
              ) : null}
              {currentRender ? (
                <div className="batch-note">
                  <span>
                    批次{" "}
                    {Math.min(
                      currentRender.next_batch_index,
                      currentRender.batch_count,
                    )}
                    /{currentRender.batch_count}
                  </span>
                  <small>
                    每批 {currentRender.batch_size} 章；本批完成后自动处理下一批
                  </small>
                </div>
              ) : null}
              {createAudio.isError ? (
                <div className="error-banner">{createAudio.error.message}</div>
              ) : null}
              {!currentRender ? (
                <div className="audio-create">
                  <label className="field compact">
                    <span>朗读音色</span>
                    <select
                      value={voice}
                      onChange={(event) => setVoice(event.target.value)}
                    >
                      <option value="zh-CN-XiaoxiaoNeural">晓晓 · 女声</option>
                      <option value="zh-CN-YunxiNeural">云希 · 男声</option>
                      <option value="zh-CN-YunjianNeural">云健 · 男声</option>
                      <option value="zh-CN-XiaoyiNeural">晓伊 · 女声</option>
                    </select>
                  </label>
                  <button
                    className="primary-button full"
                    disabled={createAudio.isPending}
                    onClick={() => createAudio.mutate()}
                  >
                    <AudioLines size={16} />
                    {createAudio.isPending ? "正在创建…" : "生成分章音频"}
                  </button>
                </div>
              ) : (
                <div className="audio-parts">
                  <div className="render-status">
                    <div>
                      <span>
                        {currentRender.status === "succeeded"
                          ? "全部完成"
                          : currentRender.status === "partial_failed"
                            ? "部分失败"
                            : "生成中"}
                      </span>
                      <small>
                        {currentRender.provider === "edge"
                          ? "Edge 人声"
                          : "Mock 测试音"}{" "}
                        ·{" "}
                        {
                          currentRender.parts.filter(
                            (part) => part.status === "succeeded",
                          ).length
                        }
                        /{currentRender.parts.length} 可播放
                      </small>
                    </div>
                    <button
                      className="regenerate-button"
                      disabled={
                        createAudio.isPending ||
                        ["pending", "running"].includes(currentRender.status)
                      }
                      onClick={() => createAudio.mutate()}
                    >
                      <RefreshCw size={14} />
                      {createAudio.isPending
                        ? "正在创建…"
                        : currentRender.provider === "mock"
                          ? "生成人声"
                          : "重新生成"}
                    </button>
                  </div>
                  {(visibleParts ?? []).map((part) => (
                    <div className="audio-row" key={part.id}>
                      <span className={`part-state ${part.status}`}>
                        {part.status === "succeeded" ? (
                          <Check size={14} />
                        ) : part.status === "failed" ? (
                          <CircleAlert size={14} />
                        ) : (
                          <LoaderCircle className="spin" size={14} />
                        )}
                      </span>
                      <div>
                        <strong>{part.title}</strong>
                        <small>
                          {part.duration_ms
                            ? `${Math.max(1, Math.round(part.duration_ms / 1000))} 秒`
                            : `${part.chunks.length} 个片段`}
                        </small>
                      </div>
                      {part.status === "succeeded" ? (
                        <audio
                          className="chapter-audio"
                          controls
                          preload="none"
                          src={audioStreamUrl(part.id)}
                        />
                      ) : null}
                      {part.status === "failed" ? (
                        <button
                          className="icon-button"
                          title="重试本章"
                          onClick={() => retryPart.mutate(part.id)}
                        >
                          <RefreshCw size={15} />
                        </button>
                      ) : null}
                    </div>
                  ))}
                  {visibleParts &&
                  visibleParts.length < currentRender.parts.length ? (
                    <div className="queued-parts-note">
                      后续 {currentRender.parts.length - visibleParts.length}{" "}
                      章将在后续批次自动处理
                    </div>
                  ) : null}
                </div>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}

function groupDocumentBlocks(blocks: ContentBlock[]): DocumentSection[] {
  const sections: DocumentSection[] = [];
  let current: DocumentSection | null = null;
  let pendingVolume: ContentBlock | null = null;

  for (const block of blocks) {
    if (block.block_type === "volume") {
      if (current) sections.push(current);
      current = null;
      pendingVolume = block;
      continue;
    }
    if (["chapter", "heading"].includes(block.block_type)) {
      if (current) sections.push(current);
      current = {
        id: block.id,
        anchorIds: pendingVolume ? [pendingVolume.id, block.id] : [block.id],
        title: pendingVolume
          ? `${pendingVolume.text} · ${block.text}`
          : block.text,
        blocks: [],
      };
      pendingVolume = null;
      continue;
    }
    if (!current) {
      current = pendingVolume
        ? {
            id: pendingVolume.id,
            anchorIds: [pendingVolume.id],
            title: pendingVolume.text,
            blocks: [],
          }
        : {
            id: block.id,
            anchorIds: [block.id],
            title: "正文开头",
            blocks: [],
          };
      pendingVolume = null;
    }
    current.blocks.push(block);
  }
  if (current) sections.push(current);
  else if (pendingVolume)
    sections.push({
      id: pendingVolume.id,
      anchorIds: [pendingVolume.id],
      title: pendingVolume.text,
      blocks: [],
    });
  return sections;
}

function renderContentBlock(block: ContentBlock) {
  const Icon = blockIcons[block.block_type];
  if (block.block_metadata.ad_candidate)
    return (
      <div className="source-block muted-block" key={block.id}>
        <small>广告候选，原文朗读中已跳过</small>
        <p>{block.text}</p>
      </div>
    );
  if (Icon)
    return (
      <div className="source-block special-block" key={block.id}>
        <div className="block-label">
          <Icon size={15} />
          {block.block_type}
          <span>来源块 {block.position + 1}</span>
        </div>
        <pre>
          {block.text || String(block.block_metadata.src ?? "无替代文本")}
        </pre>
      </div>
    );
  return (
    <p className="source-paragraph" key={block.id}>
      {block.text}
    </p>
  );
}
