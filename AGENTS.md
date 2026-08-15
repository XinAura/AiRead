# AGENTS.md

## 1. 项目概述

AiRead 是一个以后端能力为主的 AI 阅读、内容理解和有声化个人平台，不是单纯的文本转语音工具。

系统保存文章和书籍，将原始资料解析为可引用的结构化文档，再支持两条输出路径：忠实原文朗读，以及由 Agent 根据用户自然语言目标动态生成的小说精讲、人物故事线、技术专题或图文代码讲解。

前端使用 Next.js、React 和 TypeScript；后端使用 Python 3.12、FastAPI、PostgreSQL、Redis 和 Celery；音频使用 edge-tts 与 FFmpeg。所有项目运行时、依赖和中间件统一位于 WSL 环境。

仓库采用 Monorepo。`apps/web` 是前端；`backend` 是唯一 Python 后端；`packages/api-client` 是由 OpenAPI 生成的 TypeScript 客户端；`infra` 保存 Docker Compose 基础设施配置。第二阶段引入版本化提示词时再创建 `prompts`，不得提前假定该目录存在。

核心领域链路：

```text
LibraryItem
  -> SourceDocument
  -> ParsedDocument + ContentBlock
  -> AnalysisIndex
  -> AgentRun
  -> Edition
  -> AudioRender -> AudioPart -> AudioChunk
```

事实层与表达层必须分离。原文、章节、图片、代码和引用属于事实层；原文朗读稿、精讲稿和专题讲解属于表达层。任何 AI 生成的关键结论都必须能够追溯到事实层内容块。

当前仓库已完成第一阶段事实层与原文朗读闭环，包含资料导入、确定性结构解析、原文 Edition、Edge TTS、FFmpeg、分批音频任务、局部重试和响应式工作台。第二阶段的小说人物/事件索引、技术语义讲解、Agent 动态计划和讲解版生成尚未实现。权威产品规格见 `docs/specs/2026-08-14-ai-reading-agent-platform-spec.md`；新增能力必须先判断属于第一阶段维护还是第二阶段扩展，不得把计划中的 Agent 能力描述成已完成。

## 2. 快速命令

所有命令都从 WSL 中执行。仓库路径为 `/home/xin/code/AiRead`。

### 2.1 首次准备

```bash
cd /home/xin/code/AiRead
cp .env.example .env
docker compose -f infra/compose.yaml up -d postgres redis minio

cd backend
uv sync --all-extras
uv run alembic upgrade head

cd ../apps/web
corepack enable
pnpm install --frozen-lockfile
```

`infra/compose.yaml` 落地后，中间件优先使用容器，不在 WSL 全局安装 PostgreSQL、Redis 或 MinIO 服务。

### 2.2 启动后端 API

```bash
cd /home/xin/code/AiRead/backend
uv run uvicorn airead.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 2.3 启动 Celery Worker

解析与音频 Worker 必须分开启动。音频 Worker 的进程并发必须与 `AIREAD_AUDIO_JOB_CONCURRENCY` 保持一致，默认 2：

```bash
cd /home/xin/code/AiRead/backend
uv run celery -A airead.core.celery_app:celery_app worker \
  --hostname=airead-core@%h \
  --queues ingestion,parsing,agent \
  --concurrency 2 \
  --loglevel INFO

uv run celery -A airead.core.celery_app:celery_app worker \
  --hostname=airead-audio@%h \
  --queues audio \
  --concurrency 2 \
  --loglevel INFO
```

禁止重新使用一个高并发 Worker 同时监听解析和音频队列。长音频任务会占用全部子进程，并使解析任务饥饿；多余音频子进程还会在 Redis 并发槽外超时重试。

### 2.4 启动前端

```bash
cd /home/xin/code/AiRead/apps/web
pnpm dev
```

默认地址：

- 前端：`http://127.0.0.1:3000`
- API：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`
- MinIO API：`http://127.0.0.1:9000`
- MinIO Console：`http://127.0.0.1:9001`

### 2.5 中间件管理

```bash
cd /home/xin/code/AiRead
docker compose -f infra/compose.yaml ps
docker compose -f infra/compose.yaml logs -f postgres redis minio
docker compose -f infra/compose.yaml stop
docker compose -f infra/compose.yaml down
```

除非用户明确要求，不使用 `down -v`，因为它会删除数据库和对象存储卷。

### 2.6 环境变量

- 根目录 `.env.example` 保存变量名、安全默认值和说明。
- 根目录 `.env` 保存本地后端、Worker 和 Docker Compose 配置，不提交 Git。
- `apps/web/.env.local` 只能保存前端可公开配置，例如 `NEXT_PUBLIC_API_BASE_URL`，不能保存模型密钥。
- FastAPI 和 Celery 必须通过同一个 Settings 模块读取仓库根目录 `.env`，启动命令不要求手动 `source`。
- 环境变量优先级：进程环境变量 > 根目录 `.env` > 代码默认值。
- 新增必填变量时，必须同步更新 `.env.example` 和配置验证测试。

建议变量：

```text
AIREAD_ENV
AIREAD_DATABASE_URL
AIREAD_REDIS_URL
AIREAD_STORAGE_BACKEND
AIREAD_STORAGE_ROOT
AIREAD_S3_ENDPOINT
AIREAD_S3_BUCKET
AIREAD_S3_ACCESS_KEY
AIREAD_S3_SECRET_KEY
AIREAD_AI_PROVIDER
AIREAD_AI_MODEL
AIREAD_VISION_MODEL
AIREAD_AI_API_KEY
AIREAD_TTS_PROVIDER
AIREAD_TTS_GLOBAL_CONCURRENCY
AIREAD_TTS_CHUNK_CONCURRENCY
AIREAD_AUDIO_JOB_CONCURRENCY
AIREAD_AUDIO_BATCH_SIZE
AIREAD_ASSEMBLE_CONCURRENCY
AIREAD_FFMPEG_PATH
AIREAD_FFPROBE_PATH
AIREAD_DEV_ORIGIN
NEXT_PUBLIC_API_BASE_URL
```

真实 API Key、数据库密码和对象存储密钥不得写入源码、测试快照、日志或 Git。

## 3. 后端架构

### 3.1 当前目录与演进边界

```text
backend/
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── migrations/
├── scripts/                         # OpenAPI、冒烟、结构和任务检查脚本
├── tests/
└── src/airead/
    ├── api/main.py                  # 第一阶段 FastAPI 路由和响应映射
    ├── core/                        # 配置、数据库、Celery 基础配置
    ├── modules/
    │   ├── models.py                # 第一阶段共享 SQLAlchemy 持久化模型
    │   ├── library/                 # 资料库导入、来源版本和 Schema
    │   ├── documents/               # ParsedDocument、ContentBlock Schema
    │   ├── parsing/                 # 通用、小说、技术结构解析
    │   ├── editions/                # 原文 Edition 分组和 Schema
    │   ├── audio/                   # TTS、Part、Chunk、批次和拼接
    │   └── jobs/                    # PipelineRun 查询 Schema
    ├── providers/                   # TTS、Storage 和并发限制适配器
    └── workers/                     # 解析和音频 Celery 任务入口
```

第一阶段允许共享持久化模型集中在 `modules/models.py`。第二阶段新增 retrieval、agent 或独立分析索引时，只有在表所有权、迁移冲突或测试隔离出现实际问题后，才把模型拆回各业务模块。

新模块优先采用按业务能力组织的垂直切片：

```text
modules/audio/
├── models.py
├── schemas.py
├── repository.py
├── service.py
├── tasks.py
└── errors.py
```

现有模块不要求为了匹配示例立即补齐空文件。只有当替换实现、重复逻辑或测试隔离确有需要时，才增加 `repository.py`、`ports.py` 或更细的 `domain/application/infrastructure` 分层。

### 3.2 依赖方向

```text
API / Celery Task
    -> application service
        -> domain rules + repository/provider interfaces
            <- infrastructure implementations
```

- API 路由只做校验、权限、调用应用服务和响应映射。
- Celery Task 只解析任务参数、建立执行上下文、调用应用服务和处理投递级重试。
- 业务规则不得依赖 FastAPI、Celery、Redis、SQLAlchemy 或具体模型供应商。
- 模块不得直接读写其他模块拥有的数据表；通过应用服务或明确接口协作。

### 3.3 内容处理子系统

通用处理顺序：

```text
保存原始字节
  -> 编码检测与基础清洗
  -> Source Adapter
  -> ParsedDocument + ContentBlock
  -> 领域分析与证据索引
```

- TXT、Markdown、HTML 和粘贴文本是第一阶段输入。
- 小说解析器产出卷、章、人物、别名、事件、关系和时间线索引。
- 技术解析器产出概念、代码、图片、流程图、用例图、表格、公式和依赖关系。
- 规则解析先于模型语义补充。
- 原始字节、清洗文本和结构化结果分别保存，不可只保留最终文本。

### 3.4 Agent 子系统

Agent 根据用户目标动态制定计划，例如人物专线、技术专题、方案比较或指定时长讲解。

Agent 必须通过受限工具访问资料，不得直接访问服务器文件、数据库 Session 或对象存储凭证。第一版工具包括：

```text
search_blocks
read_blocks
get_chapter
find_entity_mentions
trace_events
compare_sections
inspect_image
inspect_code
get_concept_dependencies
estimate_duration
build_outline
write_edition
create_audio_render
```

所有关键结论必须保存 `source_block_ids`、引用文本、置信度和分析版本。模型推断必须与原文事实区分。

### 3.5 任务与 Worker 子系统

Celery 负责消息投递和 Worker 执行；PostgreSQL 是业务任务状态的唯一权威来源。不要把 Celery Result Backend 当作产品任务数据库。

通用任务状态：

```text
pending
running
succeeded
failed
retryable
paused
canceled
```

每个任务节点至少保存：

- 输入哈希和幂等键。
- 父节点、依赖和运行 ID。
- 尝试次数、最大次数和错误分类。
- 开始、心跳和结束时间。
- 输出资源或输出记录 ID。

Worker 必须假设消息可能重复、延迟或重新投递。任务重复执行时不得重复创建业务产物。

队列职责：

- `ingestion`：文件保存、编码检测、清洗和资源抽取。
- `parsing`：结构化解析和领域索引。
- `agent`：计划、工具调用、讲解稿和事实核验。
- `audio`：Edge TTS、音频校验和 FFmpeg 拼接。

### 3.6 音频子系统

```text
AudioRender
  -> AudioPart
      -> AudioChunk
```

- AudioPart 是章节或讲解段，是用户播放的最小完整单位。
- AudioChunk 是 TTS 内部切片，不作为前端播放列表项。
- 创建 Render 时持久化全部 Part 和 Chunk，但只投递 `batch_index = 0` 的第一批。
- 默认每批 3 个 Part，批内最多并发 2 个 Part；单 Part 最多并发 2 个 Chunk，全局 TTS 并发 3，FFmpeg 并发 1。
- 当前批全部 `succeeded` 或最终 `failed` 后才能领取下一批；`retryable` 不能提前放行。
- 下一批通过 PostgreSQL `FOR UPDATE` 行锁领取，同一批只能推进一次。
- Chunk 独立重试；Part 最终失败不阻塞后续批次。
- Part 完成后立即可播放，不等待整本书完成。
- TTS 全局并发、单 Part 并发和 FFmpeg 并发分别限制。
- 音频缓存键必须包含文本哈希、音色、语速、音调、Provider 和 Provider 版本。
- 拼接成功后可以删除临时 Chunk 文件，但必须保留状态、哈希、重试和错误审计记录。
- 音频流接口必须支持 HTTP Range、206 和非法范围 416。
- Render 或 Part 已取消时，迟到的 Celery 消息必须直接跳过，不能恢复成 `running`。
- 不得自动对长书启动真实 Edge TTS 回归；使用短 Edition 或 Mock Provider 验证批次，整书真实合成由用户主动触发。

### 3.7 数据库与迁移

- 所有结构变更通过 Alembic 迁移完成。
- 不在应用启动时调用 `create_all()` 修改生产数据库。
- 迁移文件名使用 `<revision>_<action>_<object>.py`，例如 `a1b2_create_content_blocks.py`。
- 业务事务边界放在应用服务，不放在 API 路由或 Provider 中。
- 数据库枚举状态需要兼容旧数据，修改前先设计迁移和回滚策略。
- 使用 PostgreSQL 约束和唯一索引保护幂等键、内容块位置和任务节点唯一性。

详细产品和领域规格见 `docs/specs/2026-08-14-ai-reading-agent-platform-spec.md`。

## 4. 前端架构

### 4.1 目标目录

```text
apps/web/
├── app/                             # Next.js 页面、布局和错误边界
├── components/                      # 跨功能通用组件
├── features/
│   ├── library/                     # 资料库和导入
│   ├── reader/                      # 原文和章节阅读
│   ├── agent/                       # 对话、计划、证据和讲稿
│   ├── jobs/                        # 进度、日志摘要和重试
│   └── player/                      # 音频播放和播放列表
├── lib/                             # API 客户端配置和通用工具
├── stores/                          # 播放器等少量客户端状态
└── tests/                           # 前端单元和集成测试
```

### 4.2 路由建议

```text
/
/library
/library/import
/library/[itemId]
/library/[itemId]/read
/library/[itemId]/agent
/agent/runs/[runId]
/editions/[editionId]
/jobs/[runId]
/audio/[renderId]
```

### 4.3 API 约定

- FastAPI Pydantic Schema 是接口定义的唯一事实来源。
- 后端 OpenAPI 生成 `packages/api-client`，生成代码不得手工编辑。
- 禁止在前端重复声明与后端同名的 DTO。
- TanStack Query 管理服务端状态；Zustand 只管理播放器、临时编辑状态等客户端状态。
- 任务进度第一版允许轮询，接口稳定后使用 SSE；不因实时展示需求直接引入 WebSocket。
- Route Handler 只允许做同源代理、Cookie 转换等边缘职责，不能访问数据库、Redis 或执行业务任务。

### 4.4 UI 约定

- 产品是工作台，不做营销型首页。
- 信息层级围绕资料、章节、Agent 计划、证据、任务状态和音频产物。
- 原文与 AI 补充必须有明确来源标识。
- 任务页同时展示整次运行和章节/节点进度，不能只有一个总百分比。
- 失败节点显示可理解的错误摘要和局部重试入口。
- 播放器保持稳定尺寸，支持章节列表、生成中、失败、可播放和等待下一章状态。
- 使用 Lucide 图标；未知图标需要 Tooltip；不要手绘已有图标。
- 卡片圆角不超过 8px，不嵌套装饰性卡片。
- 移动端和桌面端都必须验证文本不溢出、不遮挡、播放器不跳动。
- 小说复合标题在结构化原文中合并为“卷名 · 首章名”，不能渲染空卷区块；卷、章目录锚点都必须有效。
- 长书音频列表只展开已处理 Part 和当前批次，后续未投递 Part 用数量摘要展示。
- 窄屏使用“原文/音频”标签切换；桌面宽度使用目录、原文、音频三栏。不得为了在约 394px 的内置浏览器宽度显示三栏而破坏可读性。

## 5. 关键约定

1. **WSL 单一运行环境。** Git、Python、Node.js、uv、pnpm、虚拟环境、`node_modules`、FFmpeg、Docker CLI、构建和测试都在 WSL 中执行。不得混用 Windows 运行时或缓存。

2. **切换环境必须确认。** 更换 WSL 发行版、项目路径、全局运行时或全局配置前，先说明原因、影响和回滚方式，并取得用户确认。

3. **Windows 操作留在 Windows。** 浏览器登录态、Chrome 扩展、桌面应用、剪贴板、截图和 GUI 自动化在 Windows 执行；不要把 WSL cwd 直接传给 Windows GUI 工具。

4. **长任务不占用 HTTP 请求。** 解析、Agent、TTS 和 FFmpeg 必须通过持久化任务和 Celery Worker 执行。API 创建任务后立即返回运行 ID。

5. **PostgreSQL 保存真实状态。** Redis 和 Celery 只负责调度。页面展示、恢复和重试均以 PostgreSQL 状态为准。

6. **任务必须幂等。** 所有 Worker 任务在重复投递、进程重启和超时重试时必须安全。创建产物前检查输入哈希、状态和唯一约束。

7. **所有 AI 结论保留证据。** 小说事件、人物关系、技术结论和图表讲解必须关联内容块；无法验证时标记推断或不确定，不伪装成原文事实。

8. **Provider 必须隔离。** 业务代码不能直接依赖具体 LLM、Vision、TTS 或对象存储 SDK。通过明确接口和适配器调用。

9. **原文不可覆盖。** 原始文件、清洗稿、解析结果、分析结果和 Edition 分版本保存。重新解析或重新生成只能创建新版本或显式失效旧版本。

10. **数据库只通过迁移演进。** 修改 ORM 模型时同步添加迁移和迁移测试，不使用启动时自动建表替代迁移。

11. **前后端契约自动生成。** 修改 API Schema 后重新生成客户端，并运行后端 Schema 测试和前端类型检查。

12. **运行产物不进 Git。** `.venv`、`node_modules`、`.next`、缓存、数据库文件、Redis/MinIO 数据、用户原文、模型报告和音频全部忽略。

13. **测试覆盖失败路径。** 任务功能不仅测试成功流程，还要测试重复投递、网络失败、超时、部分失败、暂停、恢复和服务重启。

14. **保持模块化单体。** 没有可量化的独立扩缩容、故障隔离或发布需求时，不拆微服务；逻辑 Worker 可以使用不同队列和进程。

15. **整书音频必须分批。** 禁止 API 创建 Render 后循环投递全书 Part。批次大小、批内并发和全局 Provider 并发必须分别受控。

16. **版本变更必须显式。** 改变解析结构时提升 `PARSER_VERSION`；改变 Edition 分组或朗读文本时提升 `SCRIPT_VERSION`，避免错误复用旧产物。

上述约定的领域原因和验收标准见 `docs/specs/2026-08-14-ai-reading-agent-platform-spec.md`。

## 6. 本地开发及验证流程

### 6.1 标准闭环

1. 阅读规格、目标模块和邻近测试。
2. 检查 `git status --short`，保留用户现有改动。
3. 启动或确认 PostgreSQL、Redis 和 MinIO 健康。
4. 修改最小范围代码和迁移。
5. 运行模块级格式、静态检查和测试。
6. 启动 API、对应 Worker 和前端。
7. 通过 curl 验证 API，通过浏览器验证完整用户流程。
8. 再运行受影响范围的构建和集成测试。
9. 汇报变更、验证结果、未验证项和风险。

### 6.2 健康检查

```bash
curl --fail --silent http://127.0.0.1:8000/healthz
curl --fail --silent http://127.0.0.1:8000/readyz
```

- `/healthz` 只验证进程存活。
- `/readyz` 验证 PostgreSQL、Redis 和对象存储连接。
- 第一版本地单用户模式不需要 Token。引入认证后，应在本文补充获取 Token 和 curl 模板。

### 6.3 Docker 中间件检查

```bash
docker compose -f infra/compose.yaml ps
docker compose -f infra/compose.yaml exec postgres pg_isready
docker compose -f infra/compose.yaml exec redis redis-cli ping
curl --fail --silent http://127.0.0.1:9000/minio/health/live
```

Compose 服务只绑定 `127.0.0.1` 开发端口。密码来自根目录 `.env`，不能使用生产弱口令或提交到仓库。

### 6.4 日志

- 前台启动时 API、Worker 和 Web 日志输出到 stdout。标准后台开发进程分别写入 `/tmp/airead-api.log`、`/tmp/airead-worker-core.log`、`/tmp/airead-worker-audio.log` 和 `/tmp/airead-web.log`。
- Docker 日志使用 `docker compose -f infra/compose.yaml logs -f <service>`。
- 不默认写仓库内日志文件。
- 日志必须包含 `request_id`、`run_id`、`task_node_id` 和 `attempt`，但不得输出完整原文、API Key 或对象存储密钥。

常用查看命令：

```bash
tail -f /tmp/airead-api.log
tail -f /tmp/airead-worker-core.log
tail -f /tmp/airead-worker-audio.log
tail -f /tmp/airead-web.log
```

### 6.5 任务验证

任何解析、Agent 或音频任务变更都至少验证：

- 请求快速返回，不等待长任务结束。
- PostgreSQL 中创建了运行和任务节点。
- Worker 能领取并更新心跳。
- 重复投递不会产生重复产物。
- 可恢复错误按策略重试。
- 不可恢复错误保留明确错误码。
- 某章节失败不阻塞无依赖章节。
- 已完成 Part 可以在整本任务完成前播放。
- 创建 Render 后 Redis 中只有当前批次任务，不存在整书消息洪峰。
- 当前批未完成时不能领取下一批；批次完成后只能领取一次。
- 临时错误在自动重试耗尽前保持 `retryable`，不能被当作最终失败放行。
- 取消状态不会被迟到消息复活。

长书结构回归可以使用：

```bash
cd /home/xin/code/AiRead/backend
uv run python scripts/inspect_document_structure.py <document_id>
uv run python scripts/inspect_audio_runs.py <library_item_id>
```

## 7. 质量检查

命令以对应脚手架和脚本已经创建为前提。缺失脚本时，应在实现相关模块时补齐，不得静默跳过。

### 7.1 后端

```bash
cd /home/xin/code/AiRead/backend
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

数据库相关变更额外执行：

```bash
uv run alembic upgrade head
uv run alembic check
```

### 7.2 前端

```bash
cd /home/xin/code/AiRead/apps/web
pnpm format:check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

### 7.3 端到端

```bash
cd /home/xin/code/AiRead/apps/web
pnpm exec playwright test
```

### 7.4 命令矩阵

| 变更范围              | 必须验证                                    |
| --------------------- | ------------------------------------------- |
| 文档和纯注释          | Markdown 结构、链接和命令准确性             |
| FastAPI 路由或 Schema | Ruff、mypy、相关 pytest、OpenAPI 客户端生成 |
| 数据库模型            | Ruff、mypy、迁移 upgrade、repository 测试   |
| Celery 任务           | 单元测试、重复投递、失败重试、恢复测试      |
| Agent 工具或 Prompt   | Schema 测试、引用测试、固定样本回归测试     |
| TTS 或 FFmpeg         | 分片、缓存键、超时、重试、拼接和时长测试    |
| React 组件            | format、lint、typecheck、相关 Vitest        |
| 用户主流程            | 前后端构建、集成测试、Playwright            |

## 8. 参考项目约定

### 8.1 参考优先级

发生冲突时按以下顺序处理：

1. 当前用户明确要求。
2. `docs/specs/2026-08-14-ai-reading-agent-platform-spec.md`。
3. 已接受的 ADR。
4. 本文件中的工程约定。
5. 外部参考项目。

### 8.2 匠魂书音

参考仓库：`https://github.com/ALing-LingXi/jianghun-shuyin`

优先吸收：

- Book/Job/Part/Chunk 的任务拆分经验。
- Chunk 级自动重试和 Part 级手动重试。
- 部分失败不阻断其他章节。
- 章节完成后立即播放。
- TTS、任务和 FFmpeg 独立并发限制。
- HTTP Range 播放和中间音频清理。

不得直接照搬：

- 将核心后端放入 Next.js Route Handler。
- Windows 专用 `ffmpeg.exe` 路径。
- SQLite 和本地轮询 Worker 作为长期架构。
- 固定流水线替代 Agent 动态 TaskGraph。
- 将数据库、用户 TXT、报告或音频提交到 Git。

参考项目只能提供实现经验，不能覆盖本项目的领域模型和架构边界。

## 9. 文档导航

| 文档                                                      | 用途                                       | 状态           |
| --------------------------------------------------------- | ------------------------------------------ | -------------- |
| `AGENTS.md`                                               | 项目结构、命令、约束和验证流程             | 当前文件       |
| `docs/specs/2026-08-14-ai-reading-agent-platform-spec.md` | 产品范围、领域模型、Agent 和音频架构规格   | 当前基线       |
| `docs/adr/`                                               | 已接受的重要架构决策                       | 待创建         |
| `README.md`                                               | 面向开发者的安装、日志、分批策略和启动入口 | 第一阶段已完成 |

新增详细文档后必须更新本表。长期有效的工程约束放在 `AGENTS.md`；产品与领域规则放在 `docs/specs`；具有备选方案和取舍记录的技术决策放在 `docs/adr`，不要在多个文件复制整段规则。
