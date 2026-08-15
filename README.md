# AiRead

AiRead 是一个面向个人资料的 AI 阅读、结构化解析和有声化工作台。第一阶段实现资料导入、小说章节与技术内容块解析、原文朗读版、分章音频和局部重试。

权威规格：`docs/specs/2026-08-14-ai-reading-agent-platform-spec.md`。

## 本地启动

所有命令在 WSL 的 `/home/xin/code/AiRead` 下运行。

```bash
cp .env.example .env
docker compose -f infra/compose.yaml up -d postgres redis minio
cd backend
uv sync --all-extras
uv run alembic upgrade head
uv run uvicorn airead.api.main:app --reload --host 0.0.0.0 --port 8000
```

分别启动解析 Worker（后台任务执行进程）和音频 Worker。拆开队列可以防止长音频任务占满进程，音频 Worker 的 2 并发与批内并发上限保持一致：

```bash
cd /home/xin/code/AiRead/backend
uv run celery -A airead.core.celery_app:celery_app worker \
  --hostname=airead-core@%h --queues ingestion,parsing,agent \
  --concurrency 2 --loglevel INFO

uv run celery -A airead.core.celery_app:celery_app worker \
  --hostname=airead-audio@%h --queues audio \
  --concurrency 2 --loglevel INFO
```

前端：

```bash
cd /home/xin/code/AiRead/apps/web
corepack pnpm install
corepack pnpm dev
```

## 查看日志和定位任务

开发进程默认将日志写到 WSL 的 `/tmp`，分别打开终端查看：

```bash
tail -f /tmp/airead-api.log
tail -f /tmp/airead-worker-core.log
tail -f /tmp/airead-worker-audio.log
tail -f /tmp/airead-web.log
```

- API 日志用于确认请求路径、状态码和重复轮询。
- Core Worker 日志用于确认解析与朗读版本创建是否成功。
- Audio Worker 日志用于确认 TTS、重试、批次放行和 FFmpeg 是否成功。
- Web 日志用于确认页面编译、跨域警告和前端服务错误。

查看基础设施状态和日志：

```bash
docker compose -f infra/compose.yaml ps
docker compose -f infra/compose.yaml logs -f postgres redis minio
```

页面拿到 `run_id` 后可以查询持久化任务状态：

```bash
curl http://127.0.0.1:8000/jobs/<run_id>
```

音频响应中的 `provider` 应为 `edge`。若为 `mock`，说明它是开发测试音，不是真人朗读；重启 API 和 Worker 让其读取默认 Edge 配置，再从页面重新生成音频。

## 音频分批策略

整本书不会一次性把所有章节投递到 Celery。创建音频版本时会保存全部 Part 和 Chunk 状态，但只投递第 1 批：

```text
第 1 批：第 1-3 章并发生成
  -> 每章完成后立即可播放
  -> 本批全部结束
第 2 批：第 4-6 章并发生成
  -> 按相同规则继续
```

默认限制：

- `AIREAD_AUDIO_BATCH_SIZE=3`：每批 3 章。
- `AIREAD_AUDIO_JOB_CONCURRENCY=2`：最多同时生成 2 章。
- `AIREAD_TTS_CHUNK_CONCURRENCY=2`：单章最多同时合成 2 个 Chunk。
- `AIREAD_TTS_GLOBAL_CONCURRENCY=3`：所有 Worker 合计最多 3 个 TTS 请求。
- `AIREAD_ASSEMBLE_CONCURRENCY=1`：同时只运行 1 个 FFmpeg 章节拼接。

当前批次全部达到成功或最终失败后，由数据库行锁保证只有一个 Worker 能领取并投递下一批。临时网络错误在自动重试耗尽前不会提前放行；最终失败的章节不会阻塞后续批次，并且可以单独重试。

查看某本资料的音频任务和解析结构：

```bash
cd /home/xin/code/AiRead/backend
uv run python scripts/inspect_audio_runs.py <library_item_id>
uv run python scripts/inspect_document_structure.py <document_id>
uv run python scripts/cancel_pipeline_run.py <run_id>
```
