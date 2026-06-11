---
status: backlog
related: []
---

# Bug 11: AgentArts 平台级缺陷与限制汇总

本 Bug 用于统一记录与追踪 AgentArts 平台（包括 CLI、Runtime、Gateway 等组件）自身存在的问题、缺陷和功能限制。这些问题在本地开发或外部云平台（如 Netlify）部署时不存在，但在 AgentArts 环境下会产生运维噪音、安全隐患或阻碍自动化流程。

---

## 缺陷与限制列表

### 1. `GET /ping` 健康检查 Log 刷屏且无法过滤

#### 现象
容器的标准输出（stdout）中持续产生大量的 `GET /ping` 成功响应（200 OK）的 Log，例如：
```
INFO:     169.254.169.254:56856 - "GET /ping HTTP/1.1" 200 OK
```
即使在 FastAPI 层的 `uvicorn.access` Logger 中配置了 `PingFilter`，该 Log 依然源源不断地刷屏。

#### 根因
1. **容器内 Logger 过滤失效**：该 Log 极有可能并非由 FastAPI 容器内的应用程序直接通过 uvicorn access Logger 打印，而是由 AgentArts Runtime 的 Sidecar Proxy 或辅助进程（例如 APIG APIG-Agent）在转发健康检查请求时直接输出到了 stdout。
2. **过滤机制受限**：由于 Log 产生的源头超出了容器内 User Space 的控制范围（不经过 `app.main:app` 中的 Logger），应用层无法通过任何 Log 过滤器（如 `logging.Filter`）对其进行拦截。
3. **副作用**：高频刷屏的健康检查 Log 严重污染了真实的系统 Log 视图，极易掩盖真实的异常信息（如 500 错误或业务异常），大幅降低了可观测性（Observability）和排障效率。

---

### 2. `agentarts launch` 无法在线修改认证方式

#### 现象
通过修改 `.agentarts_config.yaml` 中的 `authorizer_type`（如从 `IAM` 改为 `KEY_AUTH` 或 `PUBLIC`），然后执行 `agentarts launch` 进行热更新时，新的认证配置无法生效，且 CLI 不会抛出任何错误或警告。

#### 现阶段规避方案
必须先执行 `agentarts delete`（或手动在控制台删除对应部署），然后再执行 `agentarts launch` 重新部署，认证方式的修改才能生效。

#### 根因
1. **APIG 绑定限制**：AgentArts Gateway 底层基于华为云 API Gateway（APIG）。在 APIG 中，已发布 API 的安全认证类型（Authentication Type）通常是不允许直接在发布状态下进行就地（in-place）修改的。
2. **CLI 缺乏检验与报错**：`agentarts` CLI 在执行更新部署（launch）时，没有检测 `authorizer_type` 字段的变化，也没有在底层 API 返回限制时抛出显式错误，导致配置静默失效，给开发者带来极大的误导。

---

### 3. `agentarts launch` 不支持 `--env` 或 `--env-file` 选项

#### 现象
`agentarts launch` CLI 缺乏注入环境变量（Environment Variables）的参数选项（如 `--env` 或 `--env-file`），迫使项目必须将敏感配置（如 LLM API Key、数据库连接 Secrets 等）以明文形式直接保存在 `personal-assistant-service/.agentarts_config.yaml` 的 `env_variables` 字段中。

#### 安全隐患
1. **Secrets 泄露风险**：明文保存 Secrets 会极大地增加 Secrets 泄露的风险。这些敏感信息非常容易随着代码库的 Commit、PR 提交被意外推送至 Git 远程仓库（如 GitHub）。
2. **多环境管理不便**：不支持外部环境变量注入，导致在 CI/CD 流程中无法实现代码与配置的干净分离（12-Factor App 规范）。
3. **目前进展**：已在 GitHub 官方 Repository 提交 Issue/Ticket，推进平台支持 CLI 环境变量注入或秘密管理器（Secret Manager）集成。

---

### 4. AgentArts Runtime 强行拦截并限制自定义路由

#### 现象
AgentArts Runtime 对用户在 FastAPI 中定义的自定义 URL Path 进行强行拦截或重定向，不允许用户自由定义非规范路径（如对除 `/invocations` 之外的任意 Path 进行严格限制或异常路由阻断）。

#### 根因
1. **Runtime Gateway 路由硬编码**：AgentArts 平台的 Gateway 转发层对请求 Path 存在硬编码约束（例如默认仅将特定格式的请求路由转发给后端 Container 实例，或在转发过程中剥离/修改路径段），导致常规 Web 框架（如 FastAPI、Express）在容器内运行时，无法像在标准容器环境（如 AWS App Runner、Google Cloud Run）中那样暴露通用的 Restful API。
2. **与行业标准（Industry Standard）的偏差**：相比 AWS AgentCore 或其他成熟的 Serverless 容器托管平台，这种强行拦截自定义 Path 的做法极大地限制了后端应用的架构灵活性，迫使开发者必须采用复杂的 Workaround（如嵌套代理或非标准端口路由）来适配平台。

---

## 实施任务

由于这些问题属于 **AgentArts 平台级缺陷**，我们无法通过直接修改 `personal-assistant` 本身的代码彻底根治。当前的实施任务主要是**监控平台更新**，并保持对以下临时避险（Workaround）措施的维护：

- [ ] **日志过滤临时方案**：继续在 `app/main.py` 中保留 `PingFilter`，至少过滤掉容器自身产生的 Uvicorn access 噪声。
- [ ] **部署流程文档加固**：在 `architecture/devops/agentarts-deploy-runbook.md` 中补充提示：*“修改认证方式时，必须先 delete 后 launch 才能生效”*。
- [ ] **Secrets 保护规避**：严禁在 `.agentarts_config.yaml` 中提交真实 Secrets，本地开发使用 `.env`（已加入 `.gitignore`），在 CI 部署流程中通过临时脚本动态替换 YAML 占位符。
- [ ] **路由适配保持**：统一采用 `/invocations` 作为核心 API 接口，避免在容器中暴露其他可能被 Runtime 拦截的自定义 Path。

---

## 四问闸门（Four-Question Gate）评估

> 本 Bug 文档用于记录并推动平台级改进，其分析过程和规避方案严格遵循四问准则：

| 维度 | 评估结果 | 说明 |
|------|:---:|------|
| **Is it best practice?** | **Yes** | 记录并公开追踪上游 Platform Limitations 是优秀开源项目的最佳实践。这能让未来的维护者明确区分“业务 Bug”与“平台 Bug”，避免无谓的 Debug 耗时。 |
| **Is it industry standard?** | **Yes** | 业界主流项目（如 Kubernetes 上的诸多 Operator、Terraform Providers）均会维护专门的 Upstream Limitations / Known Issues 文档来指导用户。 |
| **Is it conventional?** | **Yes** | 遵循常规的 Bug 结构，包含现象、根因和 Workaround，使新成员能立即对当前的基础设施局限性一目了然。 |
| **Is it modern?** | **Yes** | 拥抱 Infrastructure-as-Code（IaC）和可观测性（Observability）的标准，对 Log 污染、Secrets 明文存储等安全现代性缺陷进行严厉审视。 |
