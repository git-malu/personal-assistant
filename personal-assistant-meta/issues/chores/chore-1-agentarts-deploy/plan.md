# Plan: Chore 1 — 首次部署至 AgentArts Runtime 生产环境 + 前端 OBS 部署

> 本 Plan 是**运维操作手册（Operational Runbook）**。包含一个**阻塞性代码变更**（§2.5 — CORS 中间件配置，允许 OBS 域名跨域访问）和**前端 OBS 部署流程**（§9–§12）。其余步骤为部署操作。

---

## 0. Issue Evaluation

> **Re-evaluation date**: 2026-06-08. Original evaluation confirmed; minor updates for ADR-011 awareness.

| 维度 | 结果 | 说明 |
|------|------|------|
| Staleness | ✅ | 所有引用的架构文档（`cicd.md` v0.1, `agentarts.md` 2026-06-02, `overall_architecture.md` v0.3, `ADR-004`, `infra/AGENTS.md`）均存在且内容匹配当前设计。`refactor-1-consolidate-ping-routes` 和 `refactor-2-remove-web-chat-static-serving` 均在 `resolved/` 且已合并。当前 `app/main.py` 中 root-level `/ping`（L42）和 `/invocations`（L48）handlers 已存在，CORSMiddleware 尚未添加（需执行 §2.5）。`.agentarts_config.yaml` 中 entrypoint 不一致（§16.5）、MODEL_API_KEY 冗余（§16.7，ADR-011 已确认废弃）、artifact_source.commands 冗余（§16.8）均已在 plan pitfalls 中文档化 |
| Feasibility | ✅ | 部署路径明确：Docker build（ARM64）→ SWR push → agentarts launch → smoke test（后端）+ vite build → obsutil cp → OBS 静态网站（前端）。CORS 中间件为标准 FastAPI 模式。无 ADR 冲突——ADR-004 支持 FastAPI 方案，ADR-006 支持 CDKTF IaC 路径，ADR-011 不影响部署流程（仅确认 MODEL_API_KEY 废弃，与 §16.7 判断一致） |
| Completeness | ✅ | Issue 包含 12 个任务拆解，覆盖后端部署、CORS 配置、前端构建、OBS 部署、前后端冒烟验证。plan 额外提供：§2 前置检查、§15 回滚计划、§16 14 项 pitfalls troubleshooting、§17 Mermaid 序列图、§18 最终验证清单、§19 9 项后续 cleanup 任务 |
| Impact Scope | ✅ | **Service**：CORS 中间件添加（`app/main.py`，仅 2 行 import + 8 行 add_middleware 调用）。**Client**：Vite 构建 + OBS 上传。**Infra**：OBS Bucket 创建（IaC CDKTF 或手动）。**Meta**：无变更。跨域部署链路：OBS（前端）→ CORS → AgentArts Runtime（后端）。无跨层耦合风险 |

**判定：ACCEPT** → Plan 仍然有效，无需结构性修改。以下为确认记录（非 plan 修改项）：

- **ADR-011 影响**：`MODEL_API_KEY` 已被正式废弃（`config.yaml` 中 `maas` provider 仅引用 `MAAS_API_KEY`）。Plan §16.7 的「保留（无害），后续移除」判断与 ADR-011 结论一致。`MODEL_URL` / `MODEL_NAME` 仍可做 fallback（ADR-011 §99-101），plan smoke test 不受影响。
- **feature-9-deployment**：仍为 `backlog` 状态，与此 chore 无依赖关系。

---

## 1. Issue Summary

- **类型**：Chore（运维部署）
- **目标**：将 Personal Assistant 服务首次部署到 AgentArts Runtime（`cn-southwest-2`），同时将 Web Chat 前端部署到 OBS 静态托管。打通 **容器构建 → SWR 推送 → Runtime 启动** + **前端构建 → OBS 上传 → CORS 验证** 的完整链路
- **参考架构**：
  - `architecture/devops/cicd.md` — Layer 1 AgentArts 部署策略、Layer 3 OBS 触发时机
  - `architecture/cloud-service/agentarts.md` — AgentArts 平台参考
  - `architecture/overall_architecture.md` — 总体架构（前后端分离、CORS 跨域）
  - `architecture/ADR/ADR-004-fastapi-over-agentarts-runtime-app.md` — FastAPI 替代 AgentArtsRuntimeApp 的决策
  - `personal-assistant-infra/AGENTS.md` — OBS 基础设施即代码规范
- **关键文件**：
  - `personal-assistant-service/Dockerfile` — 生产镜像构建
  - `personal-assistant-service/.agentarts_config.yaml` — AgentArts Runtime 声明式配置
  - `personal-assistant-service/app/main.py` — FastAPI 应用入口（CORS 配置将加于此）
  - `personal-assistant-client/` — Web Chat 前端项目

---

## 2. Prerequisites Checklist

部署前必须逐项确认。按执行角色分为 **Agent 可验证** 和 **人工需提供** 两类。

### 2.1 Agent 可验证（文件/环境存在性）

| # | 检查项 | 验证命令 | 预期结果 |
|---|--------|---------|---------|
| P1 | 工作目录 | `pwd` | 项目根目录（包含 `personal-assistant-service/` 和 `personal-assistant-client/`） |
| P2 | Dockerfile 存在 | `ls personal-assistant-service/Dockerfile` | 文件存在 |
| P3 | .agentarts_config.yaml 存在 | `ls personal-assistant-service/.agentarts_config.yaml` | 文件存在 |
| P4 | config.yaml 存在 | `ls personal-assistant-service/config.yaml` | 文件存在 |
| P5 | Docker 已安装 | `docker version` | 输出版本信息，无错误 |
| P6 | Docker 支持 buildx | `docker buildx version` | 输出版本信息 |
| P7 | agentarts CLI 已安装 | `agentarts --version` | 输出版本号 |
| P8 | uv.lock 存在 | `ls personal-assistant-service/uv.lock` | 文件存在 |
| P9 | openssl 已安装 | `openssl version` | 输出版本信息（SWR 密码生成依赖） |
| P10 | SWR 域名可达 | `curl -s -o /dev/null -w '%{http_code}' https://swr.cn-southwest-2.myhuaweicloud.com` | 200 或 401（可达） |
| P11 | **Node.js 已安装** | `node --version` | v18+ 或 v20+（前端构建需要） |
| P12 | **npm 已安装** | `npm --version` | v9+ |
| P13 | **obsutil CLI 可用** | `obsutil version` | 输出版本号（华为云 OBS 命令行工具） |
| P14 | 前端项目存在 | `ls personal-assistant-client/package.json` | 文件存在 |

### 2.2 人工需提供（凭据/密钥）

| # | 检查项 | 说明 | 获取方式 |
|---|--------|------|---------|
| H1 | 华为云 AK/SK | `HUAWEICLOUD_SDK_AK` / `HUAWEICLOUD_SDK_SK` 环境变量 | 华为云控制台 → IAM → 我的凭证 |
| H2 | MaaS API Key | `.agentarts_config.yaml` 中 `MAAS_API_KEY` 和 `MODEL_API_KEY` 的值 | MaaS 控制台 → 模型部署 → API Key 管理 |
| H3 | DeepSeek API Key | `.agentarts_config.yaml` 中 `DEEPSEEK_API_KEY` 的值 | DeepSeek 官方控制台 |
| H4 | SWR 登录凭据 | Docker login 使用 AK/SK 生成临时密码 | 详见 Step 3 |
| H5 | IAM 子账号权限 | 需 SWR FullAccess + **OBS FullAccess** 权限（若使用子账号） | IAM 控制台 → 用户组 → 授权 |
| H6 | **OBS 操作权限** | IAM 子账号需 OBS FullAccess（创建 Bucket、上传文件） | IAM 控制台 → 用户组 → 授权 |

### 2.3 环境变量密文替换

`.agentarts_config.yaml` 中以下三处为占位符，部署前**必须替换为真实值**：

```yaml
# 🔴 部署前必须替换
environment_variables:
  - key: MAAS_API_KEY
    value: "<MaaS API Key>"        # ← 替换为真实 MaaS API Key
  - key: DEEPSEEK_API_KEY
    value: "<DeepSeek 官方 API Key>" # ← 替换为真实 DeepSeek API Key
  - key: MODEL_API_KEY
    value: "<your-maas-api-key>"    # ← 替换为真实 MaaS API Key（与 MAAS_API_KEY 通常相同）
```

> **安全提醒**：替换后的 `.agentarts_config.yaml` **切勿提交到 Git**。建议使用 `git update-index --assume-unchanged` 或在 `.gitignore` 中排除。

---

## 2.4 Pre-Deployment Code Change（已由 refactor 预完成 — 无需操作）

> ⚠️ **历史背景**：本节描述的是 `refactor/refactor-1-consolidate-ping-routes` 解决的问题。该 refactor 在 `208a9cf` 合并后，`app/main.py` 中 root-level `/ping`（line 42）和 `/invocations`（line 48）handlers 已存在，`/api/ping` 和 `/api/invocations` 端点已移除。
>
> ✅ **当前状态：NO ACTION REQUIRED — already done.** 如果你在阅读这份 runbook 时已处于 2026-06-08 之后的分支，无需执行本节任何操作。

### 原问题（已修复）

AgentArts 平台要求容器在 port 8080 提供 **root-level** 端点：

| AgentArts 期望 | 原注册（修复前） | 行为 |
|----------------|-----------------|------|
| `GET /ping` | `@app.get("/api/ping")` | `/ping` 无匹配路由 → SPA fallback 返回 HTML ❌ |
| `POST /invocations` | `@app.post("/api/invocations")` | `/invocations` 无匹配路由 → SPA fallback 返回 HTML ❌ |

**修复方案（已实施）**：在 `app/main.py` 中添加 root-level handlers，放在 StaticFiles mount 之前（`refactor/refactor-2-remove-web-chat-static-serving` 已移除了 StaticFiles mount，但 handlers 顺序无关紧要）。

### 验证（确认修复已生效）

```bash
grep -n '@app\.\(get\|post\)\("/\(ping\|invocations\)"\)' personal-assistant-service/app/main.py
# 期望输出：
# 42:@app.get("/ping")
# 48:@app.post("/invocations")
```

---

## 2.5 Pre-Deployment Code Change — CORS 中间件配置（⚠️ 必须完成）

> ⚠️ **此变更必须在 `docker build` 之前完成并提交。** 不完成此变更，前端（部署在 OBS 域名）的跨域请求将被浏览器拦截，Web Chat 无法与后端通信。

### 问题

前端部署在 OBS 静态网站域名（如 `personal-assistant-web-chat.obs.cn-southwest-2.myhuaweicloud.com`），后端在 AgentArts Runtime 域名（如 `xxx.agentarts.cn-southwest-2.myhuaweicloud.com`）。浏览器同源策略阻止跨域请求，必须在后端配置 CORS 中间件允许 OBS 域名。

### 修复方案

在 `app/main.py` 中添加 `fastapi.middleware.cors.CORSMiddleware`。插入位置：**`app = FastAPI(...)` 之后、第一个路由（`@app.get("/ping")`）之前**。

**文件**：`personal-assistant-service/app/main.py`

在 line 39 (`)`) 之后插入：

```python
from fastapi.middleware.cors import CORSMiddleware  # 需添加到顶部 import 区域（line 12 附近）

# 在 app = FastAPI(...) 之后（line 39 之后）添加：
app.add_middleware(
    CORSMiddleware,
    allow_origins=["<obs-bucket-domain>"],  # 🔴 部署时必须替换为实际 OBS 静态网站域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**import 行需要添加到文件顶部**（line 12 附近）：

```python
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # 新增
from fastapi.responses import RedirectResponse, StreamingResponse  # noqa: E402
```

### OBS 域名获取

OBS 静态网站域名格式：

```
https://<bucket-name>.obs-website.cn-southwest-2.myhuaweicloud.com
```

例如：`https://personal-assistant-web-chat.obs-website.cn-southwest-2.myhuaweicloud.com`

**注意**：静态网站托管域名与普通 OBS endpoint 不同——静态网站使用 `.obs-website.` 而非 `.obs.` 子域名。

### 验证

```bash
# 部署后，从 OBS 域名发起跨域请求验证 CORS 头
curl -sI -X OPTIONS "<runtime-domain>/ping" \
  -H "Origin: https://<bucket-name>.obs-website.cn-southwest-2.myhuaweicloud.com" \
  -H "Access-Control-Request-Method: GET"
# 期望：响应头包含 Access-Control-Allow-Origin: <obs-domain>
```

---

## 3. Deployment Execution

> 部署操作手册已提取为独立文档，便于运维人员直接使用。

完整部署流程详见 [`architecture/devops/agentarts-deploy-runbook.md`](../../architecture/devops/agentarts-deploy-runbook.md)。
