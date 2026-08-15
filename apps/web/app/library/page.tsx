"use client";

import type { paths } from "@airead/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookText,
  FileCode2,
  FilePlus2,
  Library,
  Search,
  Upload,
  X,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { api } from "@/lib/api";

type LibraryItems =
  paths["/library/items"]["get"]["responses"]["200"]["content"]["application/json"];
type ImportResult =
  paths["/library/items"]["post"]["responses"]["202"]["content"]["application/json"];

const labels: Record<string, string> = {
  novel: "小说",
  technical: "技术资料",
  article: "文章",
  unknown: "待识别",
};

export default function LibraryPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [imported, setImported] = useState<ImportResult | null>(null);
  const items = useQuery({
    queryKey: ["library"],
    queryFn: () => api<LibraryItems>("/library/items"),
  });
  const importItem = useMutation({
    mutationFn: (form: FormData) =>
      api<ImportResult>("/library/items", { method: "POST", body: form }),
    onSuccess: async (result) => {
      setShowImport(false);
      setImported(result);
      await queryClient.invalidateQueries({ queryKey: ["library"] });
    },
  });
  const filtered = useMemo(
    () =>
      (items.data ?? []).filter((item) =>
        `${item.title} ${item.author ?? ""}`
          .toLowerCase()
          .includes(search.toLowerCase()),
      ),
    [items.data, search],
  );

  return (
    <div className="workspace">
      {imported ? (
        <div className="success-toast" role="status">
          <span className="toast-check">✓</span>
          <div>
            <strong>上传成功，正在后台解析</strong>
            <small>{imported.item.title}</small>
          </div>
          <Link className="toast-link" href={`/library/${imported.item.id}`}>
            查看进度
          </Link>
          <button
            className="toast-close"
            title="关闭提示"
            onClick={() => setImported(null)}
          >
            <X size={15} />
          </button>
        </div>
      ) : null}
      <header className="page-header">
        <div>
          <p className="eyebrow">个人内容工作区</p>
          <h1>资料库</h1>
          <p className="subtle">
            保存原始资料，跟踪解析状态，并创建可追溯的朗读版本。
          </p>
        </div>
        <button className="primary-button" onClick={() => setShowImport(true)}>
          <FilePlus2 size={17} />
          导入资料
        </button>
      </header>

      <div className="toolbar">
        <label className="search-box">
          <Search size={16} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索标题或作者"
          />
        </label>
        <span className="count-label">{filtered.length} 项资料</span>
      </div>

      {items.isLoading ? (
        <div className="empty-state">正在读取资料库…</div>
      ) : null}
      {items.isError ? (
        <div className="error-banner">无法连接后端服务。</div>
      ) : null}
      {!items.isLoading && filtered.length === 0 ? (
        <div className="empty-state large">
          <span className="empty-icon">
            <Library size={28} />
          </span>
          <h2>资料库还没有内容</h2>
          <p>
            导入 TXT、Markdown 或
            HTML，系统会保留原始文件并在后台建立章节和内容块。
          </p>
          <button
            className="secondary-button"
            onClick={() => setShowImport(true)}
          >
            <Upload size={16} />
            选择文件
          </button>
        </div>
      ) : (
        <div className="item-list">
          {filtered.map((item) => (
            <Link
              className="library-row"
              href={`/library/${item.id}`}
              key={item.id}
            >
              <span
                className={`file-icon ${item.content_type === "technical" ? "technical" : "novel"}`}
              >
                {item.content_type === "technical" ? (
                  <FileCode2 size={20} />
                ) : (
                  <BookText size={20} />
                )}
              </span>
              <span className="item-copy">
                <strong>{item.title}</strong>
                <small>{item.author || "作者未填写"}</small>
              </span>
              <span className="type-badge">
                {labels[item.content_type] ?? item.content_type}
              </span>
              <span className="item-status">
                <span className="status-dot" />
                {item.status === "ready" ? "已保存" : item.status}
              </span>
              <time>
                {new Date(item.updated_at).toLocaleDateString("zh-CN")}
              </time>
            </Link>
          ))}
        </div>
      )}

      {showImport ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={() => setShowImport(false)}
        >
          <form
            className="dialog"
            onMouseDown={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault();
              importItem.mutate(new FormData(event.currentTarget));
            }}
          >
            <div className="dialog-heading">
              <div>
                <p className="eyebrow">创建资料</p>
                <h2>导入原始文件</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                title="关闭"
                onClick={() => setShowImport(false)}
              >
                ×
              </button>
            </div>
            <label className="field">
              <span>标题</span>
              <input name="title" required maxLength={500} autoFocus />
            </label>
            <label className="field">
              <span>作者</span>
              <input name="author" maxLength={300} />
            </label>
            <label className="field">
              <span>内容类型</span>
              <select name="content_type" defaultValue="novel">
                <option value="novel">小说</option>
                <option value="technical">技术书籍或文章</option>
                <option value="article">普通文章</option>
                <option value="unknown">暂不确定</option>
              </select>
            </label>
            <label className="file-drop">
              <Upload size={22} />
              <strong>选择 TXT、Markdown 或 HTML</strong>
              <small>原始文件会按内容哈希保存</small>
              <input
                name="file"
                type="file"
                required
                accept=".txt,.md,.markdown,.html,.htm,text/plain,text/markdown,text/html"
              />
            </label>
            {importItem.isError ? (
              <div className="error-banner">{importItem.error.message}</div>
            ) : null}
            <div className="dialog-actions">
              <button
                type="button"
                className="text-button"
                onClick={() => setShowImport(false)}
              >
                取消
              </button>
              <button
                className="primary-button"
                disabled={importItem.isPending}
              >
                {importItem.isPending ? "正在提交…" : "开始解析"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
