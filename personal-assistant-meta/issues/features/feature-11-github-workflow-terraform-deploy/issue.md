---
status: backlog
---

# Feature 11: GitHub Workflow + Terraform 自动化部署（Client + Service）

本 Phase 使用 GitHub Actions 建立 CI/CD 流水线，通过 Terraform（CDKTF + TypeScript）管理华为云基础资源，实现 Client（OBS + CDN）和 Service（AgentArts Runtime）的自动化构建、测试与部署。

---

## 背景

当前部署以手动操作为主：`docker build && docker push` 后执行 `agentarts launch`。随着系统复杂度增长（多渠道、前端独立托管、基础设施变更），手动部署成为瓶颈。需要建立标准化的 CI/CD 流水线，实现：

- **Client 端**：Vite + React 前端构建后自动上传到 OBS，通过 CDN 分发
- **Service 端**：Python FastAPI 后端自动构建 ARM64 镜像，推送到 SWR，触发 `agentarts launch`
- **基础设施**：通过 CDKTF（TypeScript）声明式管理华为云资源（OBS、CDN、RDS、IAM 等），Git Push 自动 plan/apply

## 范围

### GitHub Actions Workflow

- **CI（PR 触发）**：
  - Service: ruff lint + mypy type check + pytest 单元测试
  - Client: ESLint + TypeScript type check + Vitest 单元测试
  - E2E: pytest E2E 测试（可选，依赖部署环境）
- **CD（merge to main 触发）**：
  - Terraform Plan（PR 阶段）→ Terraform Apply（merge 后，基础设施变更需手动 approve）
  - Service: `docker buildx build --platform linux/arm64` → `docker push` → SWR
  - Client: `npm run build` → OBS Bucket 上传（`obsutil sync` 或 Terraform）
  - `agentarts launch` 触发 Service 容器更新
  - 冒烟测试（`/ping` + `/invocations`）

### Terraform IaC（personal-assistant-infra/）

- OBS Bucket：Web Chat 前端托管 + Terraform State Backend（`pa-terraform-state`）
- CDN 加速域名：自定义域名 + HTTPS，回源策略（`/api/*` → Service 容器，`/*` → OBS）
- RDS：PostgreSQL 实例（用户映射、持久化数据）
- IAM Agency / Role / Policy：STS Provider 授权
- VPC / EIP / Subnet：Service 网络配置

### 部署触发策略

| 组件 | 目标平台 | 触发条件 |
|------|----------|----------|
| Service 容器 | AgentArts Runtime（华为云） | merge to main，Service 目录变更 |
| Client 静态资源 | OBS + CDN（华为云） | merge to main，Client 目录变更 |
| 基础设施 | Terraform（CDKTF） | merge to main，infra 目录变更（手动 approve） |

## 不涉及

- MaaS 模型部署自动化（变更频率极低，保持手动）
- 飞书 / OfficeClaw 渠道的部署逻辑（渠道配置在 AgentArts 层，见 `agentarts_config.yaml`）
- 多环境（dev / staging / prod）— 初期仅 prod 单环境

## 任务拆解

### 11.1 Terraform Backend 与基础配置

- [ ] `personal-assistant-infra/` 目录初始化（CDKTF + TypeScript，已在 ADR-006 确定）
- [ ] Terraform State Backend：OBS `pa-terraform-state` bucket
- [ ] Provider 配置（`huaweicloud` provider，AK/SK 通过 CI Secret 注入）

### 11.2 Client 静态托管资源

- [ ] OBS Bucket（`personal-assistant-web-chat`）— public-read + website hosting（`index.html` 为默认文档）
- [ ] CDN 加速域名（`chat.personal-assistant.example.com`）
- [ ] CDN 回源策略：`/api/*` → Service 容器，`/*` → OBS Bucket
- [ ] SSL 证书（CDN 托管或手动上传）

### 11.3 Service 相关资源

- [ ] RDS PostgreSQL 实例
- [ ] VPC + Subnet + EIP（如需 PUBLIC 网络模式）
- [ ] IAM Agency / Role（STS Provider 授权）

### 11.4 GitHub Actions Workflow

- [ ] `.github/workflows/ci.yml` — PR 触发：lint + type check + unit test（Client + Service 并行）
- [ ] `.github/workflows/cd.yml` — merge to main 触发：
  - [ ] Terraform Plan（PR 阶段，plan 结果 comment 到 PR）
  - [ ] Terraform Apply（merge 后，infra 变更需手动 approve）
  - [ ] Service：ARM64 镜像构建（`docker buildx`）
  - [ ] Service：镜像推送 SWR
  - [ ] Client：Vite 构建（`npm run build`）
  - [ ] Client：上传 OBS（`obsutil sync` 或 Terraform `local-exec`）
  - [ ] `agentarts launch` 触发容器更新
  - [ ] 冒烟测试：`curl /ping` + `/invocations`

### 11.5 CI/CD 环境配置

- [ ] GitHub Secrets / Environments 配置：
  - `HUAWEICLOUD_AK` / `HUAWEICLOUD_SK` — Terraform 认证
  - `SWR_REGISTRY` / `SWR_NAMESPACE` / `SWR_PASSWORD` — 镜像仓库认证
  - `AGENTARTS_ENDPOINT` — AgentArts API 地址
- [ ] GitHub Actions Runner：ARM64 机器或 QEMU 模拟（`docker buildx` + `qemu-user-static`）

### 11.6 验证

- [ ] PR 提交 → CI 自动运行 lint + test，结果在 PR Checks 可见
- [ ] merge to main → Client 静态资源自动更新到 OBS
- [ ] merge to main → Service 镜像自动构建推送 + `agentarts launch` 触发
- [ ] 部署后 Web Chat 正常访问（CDN 域名 + HTTPS）
- [ ] Terraform state 正确存储在 OBS backend，`cdktf diff` 正常工作

## 依赖

- Feature 1.1（Web Chat 前端工程化）— Client 构建产物
- Feature 1.2（PostgreSQL 数据库）— RDS 资源定义
- Feature 1（Agent 骨架）— Service 镜像
- Feature 9（部署上线与全链路可观测）— 手动部署路径为自动化部署的基线

## 参考

- `architecture/devops/cicd.md` — CI/CD 分层策略与工具选型
- `architecture/ADR/ADR-006-iac-cdktf-typescript.md` — CDKTF 选型
- `personal-assistant-infra/AGENTS.md` — IaC 目录规范与常用命令
