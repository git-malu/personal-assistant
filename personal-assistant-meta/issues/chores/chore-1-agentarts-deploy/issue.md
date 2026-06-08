---
status: backlog
---

# Chore 1: 首次部署至 AgentArts Runtime 生产环境 + 前端 OBS 部署

将 Personal Assistant 服务首次部署到 AgentArts Runtime（`cn-southwest-2`），同时将 Web Chat 前端部署到 OBS 静态托管。打通 **容器构建 → SWR 推送 → Runtime 启动** + **前端构建 → OBS 上传 → CORS 验证** 的完整链路。

---

## 背景

项目已完成核心骨架开发（Feature 1 Agent Skeleton）和 Web Chat 前端工程化（Feature 1.1），`.agentarts_config.yaml` 和 `Dockerfile` 均已就位。当前服务架构：

- **FastAPI**：提供 `/ping` 健康检查、`/invocations` 同步调用、`/api/chat/stream` SSE 流式对话
- **Chainlit Playground**：挂载在 `/playground`，作为 Agent 调试 UI，通过 `mount_chainlit` 与 FastAPI 共享进程

前端 Web Chat（`personal-assistant-client/`）为独立 Vite + React 项目，部署到 OBS 静态托管，通过 CORS 跨域访问 AgentArts Runtime 后端。

---

## 范围

### 后端（AgentArts Runtime）

- **Docker 镜像构建**：ARM64 架构镜像（`linux/arm64`）
- **SWR 推送**：推送到 `swr.cn-southwest-2.myhuaweicloud.com/personal-assistant-org/agent_personal_assistant`
- **agentarts launch**：在 AgentArts 控制台启动 Runtime 实例
- **冒烟验证**：
  - `/ping` 健康检查
  - `/invocations` 同步对话调用
  - `/api/chat/stream` SSE 流式对话
  - `/playground` Chainlit UI 可访问
- **环境变量配置**：MaaS API Key、DeepSeek API Key 等密文注入
- **可观测性确认**：Tracing / Metrics / Logs 控制台可查看
- **CORS 配置**：允许 OBS 域名跨域访问

### 前端（OBS 静态托管）

- **前端构建**：`vite build` → `personal-assistant-client/dist/`
- **OBS Bucket 创建**：`personal-assistant-web-chat`（public-read）
- **静态网站托管配置**：index_document + error_document 指向 `index.html`
- **前端上传**：将 `dist/` 产物同步到 OBS Bucket
- **冒烟验证**：浏览器访问 OBS 域名 → 加载前端 → 发送消息成功（跨域）

---

## 前置条件 / 依赖

| 前置项 | 状态 | 说明 |
|--------|------|------|
| `Dockerfile` 可用 | ✅ 已有 | `personal-assistant-service/Dockerfile`，基于 `uv:python3.12-bookworm` |
| `.agentarts_config.yaml` 配置完整 | ✅ 已有 | entrypoint、SWR、network、observability 均已配置 |
| Web Chat 前端可构建 | ✅ 已有 | `personal-assistant-client/`，Vite + React + TypeScript + Tailwind |
| 华为云 AK/SK 认证 | ❓ 需确认 | `HUAWEICLOUD_SDK_AK` / `HUAWEICLOUD_SDK_SK` 环境变量（用于 `agentarts launch` + OBS 操作） |
| `agentarts` CLI 安装 | ❓ 需确认 | `pip install agentarts-sdk` |
| Docker 环境（ARM64） | ❓ 需确认 | 本地 ARM64 机器或 buildx QEMU 模拟；Docker < 27 或设置 `BUILDKIT_USE_OCI_MEDIA_TYPES=0` |
| SWR 组织/仓库已创建 | ✅ auto_create | `organization_auto_create: true` + `repository_auto_create: true` |
| MaaS API Key 有效 | ❓ 需确认 | `MAAS_API_KEY` 环境变量 |
| DeepSeek API Key 有效 | ❓ 需确认 | `DEEPSEEK_API_KEY` 环境变量 |
| OBS 操作权限 | ❓ 需确认 | IAM 账号需 OBS FullAccess 权限 |
| OBS 工具 | ❓ 需确认 | `obsutil` CLI 或华为云 Console 操作 |
| IaC 基础设施 | ❓ 需确认 | `personal-assistant-infra/` CDKTF 配置，用于创建 OBS Bucket |

---

## 任务拆解

### 1. 前置环境检查

- [ ] 确认 `agentarts` CLI 已安装（`agentarts --version`）
- [ ] 确认华为云 AK/SK 已配置（`echo $HUAWEICLOUD_SDK_AK`）
- [ ] 确认 Docker 环境可用（`docker version`），且支持 `linux/arm64`
- [ ] 确认 Docker 版本 < 27，或已设置 `export BUILDKIT_USE_OCI_MEDIA_TYPES=0`
- [ ] 确认工作目录为项目根目录
- [ ] 确认 Node.js 环境可用（`node --version`，前端构建需要）
- [ ] 确认 OBS 操作工具可用（`obsutil version` 或华为云 Console 可访问）

### 2. 构建 Docker 镜像（后端）

- [ ] 在项目根目录执行 ARM64 镜像构建：
  ```bash
  docker build --platform linux/arm64 \
    -f personal-assistant-service/Dockerfile \
    -t swr.cn-southwest-2.myhuaweicloud.com/personal-assistant-org/agent_personal_assistant:latest \
    .
  ```
- [ ] 验证镜像构建成功（`docker images | grep agent_personal_assistant`）

### 3. 推送至 SWR（后端）

- [ ] 登录 SWR：
  ```bash
  docker login swr.cn-southwest-2.myhuaweicloud.com
  ```
  （用户名：`cn-southwest-2@<AK>`，密码：通过 `printf "$AK" | openssl dgst -binary -sha256 -hmac "$SK" | od -An -vtx1 | sed 's/[^ ]*//g' | sed 's/ //g'` 生成）
- [ ] 推送镜像：
  ```bash
  docker push swr.cn-southwest-2.myhuaweicloud.com/personal-assistant-org/agent_personal_assistant:latest
  ```

### 4. AgentArts Launch 部署（后端）

- [ ] 在 `personal-assistant-service/` 目录下执行：
  ```bash
  agentarts launch
  ```
- [ ] 确认控制台输出 Runtime 访问域名
- [ ] 在 AgentArts 控制台确认 Runtime 实例状态为「运行中」

### 5. CORS 配置（后端）

- [ ] 在 FastAPI 中添加 CORS 中间件，允许 OBS 域名：
  ```python
  from fastapi.middleware.cors import CORSMiddleware

  app.add_middleware(
      CORSMiddleware,
      allow_origins=["<obs-bucket-domain>"],  # OBS 静态网站域名
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- [ ] 重新构建镜像并 `agentarts launch` 更新（或确保 CORS 配置已包含在镜像中）

### 6. 冒烟验证（后端）

- [ ] 健康检查：
  ```bash
  curl -s <runtime-domain>/ping
  ```
  期望返回：`{"status": "ok"}`

- [ ] 同步对话调用：
  ```bash
  curl -s -X POST <runtime-domain>/invocations \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer <api-key>" \
    -d '{"message": "你好，请简单介绍一下你自己"}'
  ```
  期望返回：包含 `response` 字段的 JSON

- [ ] SSE 流式对话：
  ```bash
  curl -s -N <runtime-domain>/api/chat/stream?q=你好 \
    -H "Accept: text/event-stream"
  ```
  期望：持续输出 `data:` 行，最终以 `data: [DONE]` 结束

- [ ] Chainlit Playground：
  ```bash
  curl -sI <runtime-domain>/playground/
  ```
  期望：HTTP 200

### 7. 可观测性确认（后端）

- [ ] 在 AgentArts 控制台「观测 > 全链路 Trace」查看部署后产生的 Trace
- [ ] 确认 Metrics 面板有数据（QPS、延迟等）
- [ ] 确认「日志」页面可查看容器 stdout/stderr 输出

### 8. 环境变量密文确认（后端）

- [ ] 确认以下环境变量已正确注入且不可在日志/控制台明文泄露：
  - `MAAS_API_KEY`
  - `DEEPSEEK_API_KEY`
  - `MODEL_API_KEY`
  - `MODEL_NAME`
  - `MODEL_URL`

### 9. 前端构建

- [ ] 安装前端依赖：
  ```bash
  cd personal-assistant-client && npm install
  ```
- [ ] 构建生产产物：
  ```bash
  npm run build
  ```
- [ ] 确认 `personal-assistant-client/dist/` 产出物完整（`index.html` + JS/CSS bundle）

### 10. OBS Bucket 创建与配置（前端）

- [ ] 创建 OBS Bucket（通过 IaC 或控制台）：
  - Bucket 名称：`personal-assistant-web-chat`
  - 区域：`cn-southwest-2`
  - ACL：`public-read`
- [ ] 配置静态网站托管：
  - Index document：`index.html`
  - Error document：`index.html`（SPA 路由回退）
- [ ] 记录 OBS 静态网站访问域名

### 11. 前端上传至 OBS

- [ ] 将 `dist/` 内容上传到 OBS Bucket：
  ```bash
  obsutil cp personal-assistant-client/dist/ obs://personal-assistant-web-chat/ -r -f
  ```
- [ ] 验证文件可公开访问：
  ```bash
  curl -sI <obs-bucket-domain>/index.html
  ```
  期望返回 HTTP 200

### 12. 前端冒烟验证

- [ ] 浏览器访问 OBS 静态网站域名 → 页面正常加载
- [ ] 发送一条对话消息 → SSE 流式返回正常（跨域请求成功）
- [ ] 检查浏览器 DevTools Console 无 CORS 错误
- [ ] 多轮对话正常（不串消息、不崩溃）

---

## 注意事项 / Pitfalls

### ARM64 / Docker

1. **ARM64 强制要求**：AgentArts Runtime 仅支持 `linux/arm64`。若本地为 X86 机器，需使用 `docker buildx` + QEMU：
   ```bash
   docker buildx create --use --name arm64-builder
   docker buildx build --platform linux/arm64 --load -t <image> .
   ```

2. **OCI 格式不兼容**：Docker 27+ 默认生成 OCI 格式镜像，SWR 不支持。构建前务必设置：
   ```bash
   export BUILDKIT_USE_OCI_MEDIA_TYPES=0
   ```

### 认证与权限

3. **IAM 权限**：若使用 IAM 子账号，需确保有 SWR FullAccess + OBS FullAccess 权限。

4. **Python 版本**：AgentArts Runtime 要求 Python ≥ 3.10（当前使用 3.12 ✅）。

5. **Region 锁定**：AgentArts Runtime 和 OBS Bucket 均使用 `cn-southwest-2`（西南贵阳一）。

### 服务架构

6. **Chainlit 挂载**：`mount_chainlit` 在 `main.py` 中调用，与 FastAPI 共享同一进程。冒烟验证时 `/playground/`（带 trailing slash）为正确访问路径。

### 前端 OBS 部署

7. **SPA 路由回退**：OBS 静态网站必须配置 `error_document: index.html`，否则直接访问非根路径（如 `/chat`）会 404。

8. **CORS**：前端在 OBS（不同域），后端在 AgentArts Runtime（另一个域），跨域请求必须配置 CORS。

9. **缓存策略**：前端 JS/CSS bundle 带 content hash（Vite 默认），可设置长缓存 `Cache-Control: max-age=31536000`。`index.html` 应设置短缓存或 no-cache。

10. **OBS 工具选择**：
    - `obsutil` CLI（华为云官方，推荐）
    - CDKTF（`personal-assistant-infra/`，创建 Bucket + 配置）
    - 华为云 Console（手动操作）

11. **前端 API base URL**：构建前需确保 Vite 环境变量（`VITE_API_BASE_URL`）指向 AgentArts Runtime 域名（跨域时需完整 URL，不能是相对路径 `/api`）。

---

## 参考

| 文档 | 路径 |
|------|------|
| AgentArts 平台架构 | `architecture/cloud-service/agentarts.md` |
| 总体架构 | `architecture/overall_architecture.md` |
| CI/CD 部署策略 | `architecture/devops/cicd.md` |
| 部署配置 | `personal-assistant-service/.agentarts_config.yaml` |
| Dockerfile | `personal-assistant-service/Dockerfile` |
| 前端项目 | `personal-assistant-client/` |
| IaC 基础设施 | `personal-assistant-infra/AGENTS.md` |
| Feature 9 部署规划 | `issues/features/feature-9-deployment/issue.md` |
| Feature 1.1 Web Chat 前端 | `issues/features/resolved/feature-1.1-web-chat-frontend/issue.md` |
