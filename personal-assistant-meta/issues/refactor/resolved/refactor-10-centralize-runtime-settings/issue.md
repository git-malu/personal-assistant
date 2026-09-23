---
status: done
supersedes:
  - refactor-3-llm-provider-config
---

# Refactor 10: 统一配置入口并清理遗留配置体系

对 Service 配置体系进行一次 breaking refactor：用户只从 `.env.example` 发现和
配置应用，代码只从 typed `Settings` 读取 Runtime 配置，Secret 只由 AgentArts
Identity 管理。删除根目录 `config.yaml`、legacy 环境变量、fallback 和重复配置
路径，不为旧设计保留兼容层。

本 issue 吸收并取代
[Refactor 3: LLM Provider 静态配置体系](../../backlog/refactor-3-llm-provider-config/issue.md)。

---

## 一句话心智模型

> 配置应用先看 `.env.example`；本地复制为 `.env`，生产注入同名环境变量；
> Secret 按其中指引配置到 AgentArts Identity。其他文件都不是用户配置入口。

```mermaid
flowchart TD
    User["开发者 / Operator<br/>需要配置应用"] --> Entry["唯一入口<br/>.env.example"]
    Entry -->|"本地"| Local["复制为 .env"]
    Entry -->|"生产"| Runtime["注入同名 Runtime 环境变量"]
    Entry -->|"Secret"| Identity["按注释配置 AgentArts Identity"]

    Local --> Settings["app/settings.py<br/>内部读取实现"]
    Runtime --> Settings
    Identity --> SDK["AgentArts Identity SDK"]
    Catalog["app/provider_catalog.py<br/>typed 内置元数据"] --> Domain["Provider Loader"]
    Settings --> App["Application"]
    SDK --> Domain
    Domain --> App
```

`app/settings.py` 和 `app/provider_catalog.py` 都是内部代码，不是配置文件。
README 和其他文档不得把用户引导到这两个文件
修改配置。

## 为什么需要大重构

当前配置存在四类认知和工程问题：

1. **没有唯一入口**：根目录同时出现 `.env.example`、`config.yaml` 和
   `.agentarts_config.yaml`，代码中又有 `settings`/Loader 概念，使用者无法判断
   应修改哪里。
2. **同一意图存在多条路径**：LLM model 和 endpoint 同时可由 `config.yaml`、
   `MODEL_NAME`、`MODEL_URL` 等路径控制；历史测试还保留 `MODEL_API_KEY` 和
   `MAAS_API_KEY` fallback 假设。
3. **配置读取散落且有副作用**：`main.py`、`logging_config.py`、
   `agent_handler.py`、`llm_config.py` 分别读取 `os.environ`，`main.py` import
   时执行 `load_dotenv()` 并污染 pytest 进程。
4. **配置、内置元数据和 Secret 混为一谈**：Provider endpoint、用户选择、
   credential provider reference 和真实 credential 没有清晰边界。

本重构不追求“继续兼容所有旧入口”。兼容层会延长混乱，因此旧入口必须删除，
旧变量即使被设置也不得继续生效。

## 目标配置模型

### 用户只面对 `.env.example`

`.env.example` 是完整的 Configuration Catalog，按领域分组列出：

- 配置名
- 用途和默认值
- 是否必填
- 可选值
- 本地填写方式
- 生产注入位置
- 若为 Secret，明确指出对应的 AgentArts Identity provider，而不提供 Secret 字段
- 冲突关系和示例

建议结构：

```dotenv
# =============================================================================
# Application
# Local: copy this file to .env
# Production: inject the same variable names into AgentArts Runtime
# =============================================================================
LOG_LEVEL=INFO

# =============================================================================
# LLM
# Credential value is NOT stored here.
# Configure an AgentArts API Key provider with the name in
# LLM_CREDENTIAL_PROVIDER.
# =============================================================================
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-pro
LLM_CREDENTIAL_PROVIDER=DEEPSEEK_API_KEY

# =============================================================================
# Persistence — choose at most one
# =============================================================================
SQLITE_DB_PATH=.data/checkpoints.db
# POSTGRES_DSN=postgresql://user:password@localhost:5432/personal_assistant
```

示例中的精确变量集合需由 Meta Implementation Plan 在完整 inventory 后冻结；
但命名必须面向领域、无 legacy alias，且本地与生产使用完全相同的变量名。

### 内部配置分层

| 类型 | 存储/入口 | 用户是否编辑 | 示例 |
|------|-----------|:------------:|------|
| Runtime 选择与参数 | `.env` / Runtime env → `Settings` | Yes | LLM 选择、日志、Persistence |
| Secret value | AgentArts Identity | 通过平台配置 | API Key、OAuth token/client secret |
| 内置 Provider 元数据 | `app/provider_catalog.py` | No | 默认 endpoint、capabilities、protocol |
| 平台部署声明 | `.agentarts_config.yaml` | 仅部署维护者 | Runtime、Gateway、认证、env 注入映射 |
| typed 读取实现 | `app/settings.py` | No | Pydantic model、validator、cached factory |

`.agentarts_config.yaml` 无法消失，因为它是 AgentArts 平台的 deployment
declaration，而不是应用配置文件。为避免双重维护：

- 应用配置值不得在其中另设不同名称
- 能由 Runtime 注入的值统一引用与 `.env.example` 相同的变量名
- 硬编码平台 ID、Gateway auth 等平台字段继续留在该文件
- README 明确区分“配置应用”和“部署 AgentArts 平台”

## 设计决策

### 1. 删除根目录 `config.yaml`

当前 `config.yaml` 同时包含 LLM Provider metadata 和 Identity provider reference，
容易被理解为应用的第二配置入口。本重构删除该文件，不改名后继续放在根目录。

内容按性质迁移：

| 当前内容 | 目标位置 |
|----------|----------|
| `llm.default` | `LLM_PROVIDER` Runtime setting |
| 当前 model 选择 | `LLM_MODEL` Runtime setting |
| 当前 credential provider name | `LLM_CREDENTIAL_PROVIDER` Runtime setting |
| 稳定的 Provider endpoint/capabilities/defaults | `app/provider_catalog.py` |
| Gitee/GitHub/M365/IAM provider reference | typed Settings，均在 `.env.example` 可发现 |
| Agency session、region、endpoint 等可部署参数 | typed Settings；确属固定协议常量的留在代码 catalog |

`provider_catalog.py` 必须：

- 使用 frozen Pydantic model + typed constant
- 只保存非敏感、随 code review 和 release 的内置元数据
- 禁止无类型 `dict` 在业务代码中传播
- Provider 不存在或 schema 非法时启动失败
- 不再创建 YAML/TOML catalog，避免形成第二个用户配置入口

### 2. Pydantic Settings 是唯一 Runtime 读取入口

新增 `app/settings.py`：

- 使用 `pydantic-settings` 和 Pydantic v2
- 声明所有 Service Runtime configuration
- 显式配置项目根目录 `.env` 路径，不依赖 process working directory
- 环境变量覆盖 `.env`，默认值优先级最低
- 使用 field/model validators 做枚举、URL、列表和交叉字段验证
- Settings 实例视为 immutable，并由带类型的 `@lru_cache` factory 提供
- 提供测试 fixture 清理 cache；测试不得依赖 module reload 触发重新读取
- ValidationError 可显示字段和约束，但不得泄露 Secret

迁移完成后，Service production code 中不得直接通过 `os.getenv()` /
`os.environ` 读取应用配置。操作系统交互或第三方 SDK 明确要求的环境变量必须在
Implementation Plan 单独列出并说明理由。

### 3. 移除 dotenv 全局副作用

- 删除 `app/main.py` 顶层 `load_dotenv()`
- 删除 Service 对 `python-dotenv` 的直接依赖
- 将 `pydantic-settings` 设为直接依赖
- production image 不复制 `.env`
- `.env` 和所有环境专用 dotenv 文件保持 gitignored

### 4. LLM 配置吸收 Refactor 3，但不延续旧设计

Refactor 3 的目标——完整 Provider 配置、默认 Provider 合理化、淘汰旧变量——
并入本 issue，但按照“唯一用户入口”重新设计：

- 默认 Provider 保持 `deepseek`
- 常用 Runtime 选择在 `.env.example` 中公开
- Provider 的稳定能力元数据进入内部 catalog
- `llm_config.py` 改为消费 typed Settings + validated catalog
- AgentArts Identity SDK 继续提供 API Key，不把 credential value 放入 Settings
- `timeout` 作为网络可靠性保护使用 `LLM_TIMEOUT_SECONDS` Setting
- `temperature`、`top_p`、`max_tokens` 不由应用层覆盖，使用 Provider/model 默认值
- `capabilities` 等随 Provider release 的元数据放入内部 catalog
- `weight` 只有在 Refactor 5 动态路由落地时才引入，避免为未实现能力提前配置

### 5. 配置错误统一 fail fast

```mermaid
flowchart TD
    Start["Service startup"] --> Settings["加载 typed Settings"]
    Settings --> Valid{"字段、枚举和交叉约束有效？"}
    Valid -->|"No"| Error["启动失败<br/>指出变量名与修复方式"]
    Valid -->|"Yes"| Catalog["加载并校验 internal catalog"]
    Catalog --> Known{"选择的 Provider / Integration 存在？"}
    Known -->|"No"| Error
    Known -->|"Yes"| Ready["启动 Application"]
```

至少覆盖：

- 非法 `LOG_LEVEL`
- 非法 URL
- `POSTGRES_DSN` 与 `SQLITE_DB_PATH` 同时设置
- 未知 LLM Provider
- 缺失 credential provider reference
- Runtime setting 与 internal catalog 不一致
- Secret provider 不可用时给出 AgentArts Identity 配置指引

## 必须删除的遗留项

本次不提供 deprecation window，不保留 alias/fallback：

| 遗留项 | 处理 |
|--------|------|
| 根目录 `config.yaml` | 删除，内容按上述规则迁移 |
| `MODEL_API_KEY` | 删除所有代码、部署、测试和文档引用 |
| `MODEL_NAME` | 删除；由 canonical `LLM_MODEL` 取代 |
| `MODEL_URL` | 删除；内置 endpoint 进入 catalog；如确需 custom endpoint，使用明确的新 canonical 名称 |
| `MAAS_API_KEY` / `DEEPSEEK_API_KEY` 作为明文环境变量读取 | 删除；credential value 只由 AgentArts Identity SDK 获取 |
| `CORS_ALLOWED_ORIGINS` | 删除所有代码、部署、测试和 current documentation 引用 |
| FastAPI `CORSMiddleware` | 删除；Web Chat 只通过 same-origin proxy 访问 Service，不再支持浏览器跨 Origin 直连 |
| “config.yaml 缺失则读取旧 env” fallback | 删除 |
| `load_dotenv()` | 删除 |
| Consumer 中的直接 `os.getenv()` / `os.environ` | 删除，统一通过 Settings |
| 测试中的 dummy legacy API Key 环境变量 | 删除，改为 mock AgentArts Identity boundary |
| 文档中“仍兼容读取”“后续移除”等过渡描述 | 删除，architecture 只描述最终事实 |
| 已失效的 MaaS 默认 Provider 和旧 schema 示例 | 删除或更新为最终设计 |

对 legacy 变量的验收语义是：即使设置它们，应用也完全忽略；repository 内除
迁移说明/历史 resolved issue 外，不再出现 production、test、deployment 或
architecture 引用。

## 完整范围

### Service

- [ ] 新增 typed `app/settings.py`
- [ ] 新增 internal Provider/Integration catalog 及其 Pydantic schema
- [ ] 删除根目录 `config.yaml`
- [ ] 重构 `llm_config.py`，吸收 Refactor 3 并删除 legacy override/fallback
- [ ] 重构 `identity.py` 及 tools，统一读取 Integration provider settings
- [ ] 重构 `main.py`、`logging_config.py`、`agent_handler.py`
- [ ] 从 `main.py` 删除 `CORSMiddleware`、默认 Origin 和 CORS 配置解析
- [ ] 移除 `load_dotenv()`、直接 Runtime env 读取和 legacy constants
- [ ] 更新 `pyproject.toml` 与 lockfile
- [ ] 将 `.env.example` 重写为唯一、完整、分组清晰的 Configuration Catalog
- [ ] 更新 Service README，只把用户引向 `.env.example`

### AgentArts deployment

- [ ] 清理 `.agentarts_config.yaml` 中 `MODEL_NAME`、`MODEL_URL`、
      `CORS_ALLOWED_ORIGINS` 等 legacy env
- [ ] Runtime env 映射统一使用 canonical names
- [ ] 审计硬编码 API Key、client ID、tenant ID 和 provider references
- [ ] Secret value 不得进入 committed YAML；平台暂不支持安全引用的字段必须在
      Implementation Plan 明确 blocking risk 和部署注入方案
- [ ] 保持 Gateway/Runtime 平台字段与应用 Settings 分离

### Tests / E2E

- [ ] 删除依赖 `MODEL_*`、`MAAS_API_KEY`、`DEEPSEEK_API_KEY` fallback 的测试
- [ ] mock AgentArts Identity SDK boundary，不通过环境变量伪造 credential
- [ ] Settings 测试覆盖默认值、env override、dotenv、validators 和 cache reset
- [ ] Catalog schema 和未知 Provider 测试
- [ ] production-like 无 `.env` 启动测试
- [ ] legacy 变量无效测试
- [ ] 删除 CORS 配置行为测试；保留 same-origin proxy 的 Client/Service E2E 覆盖
- [ ] 更新 Checkpointer、LLM、Identity 和 startup E2E tests

测试 runner 自身的控制变量（例如 `SERVICE_URL`、`RUN_*`、`E2E_*`）属于测试工具
配置，不纳入 Service Settings；必须在测试文档中与应用配置明确区分。

### Meta / Documentation

- [ ] 更新 `architecture/backend_architecture.md`
- [ ] 更新 `architecture/overall_architecture.md`
- [ ] 更新 `architecture/session-state-management.md`
- [ ] 更新 `architecture/devops/local-development.md`
- [ ] 更新 `architecture/external-systems/agentarts.md`
- [ ] amend `ADR-011`，记录根目录 `config.yaml` 和 legacy env 已退出最终架构
- [ ] 审计其他 ADR、runbook、README 和 issue plan 中仍被当作当前事实的旧配置
- [ ] 历史 issue 可保留历史记录，但必须明确其状态，不得被 current architecture
      引用为配置指南

## 非目标

- 不保留旧变量 alias、warning period 或 compatibility shim
- 不引入 Dynaconf 或另一套 Runtime configuration framework
- 不实现 `.env.dev` / `.env.prod` profile 自动选择
- 不把 Secret value 放入 `.env.example`、catalog 或 committed deployment YAML
- 不在本 issue 实现 Refactor 5 的动态路由算法
- 除明确删除浏览器跨 Origin 直连能力外，不改变外部 HTTP API contract、Agent
  行为或 Gateway routing
- 不把 client-side Vite 配置合并进 Service Settings；Client 配置需保持独立边界，
  但根 README 应明确两者入口

## 影响范围与 GitNexus 要求

预期至少涉及：

| Area | 文件/模块 |
|------|-----------|
| Settings | `app/settings.py`、`.env.example` |
| LLM | `app/llm_config.py`、internal catalog、`config.yaml` 删除 |
| Identity/Tools | `app/identity.py`、GitHub/Gitee/IAM/M365 tools |
| Runtime | `app/main.py`、`app/logging_config.py`、`app/agent_handler.py` |
| Packaging | `pyproject.toml`、`uv.lock`、Dockerfile |
| Deployment | `.agentarts_config.yaml` |
| Tests | Service tests、E2E config/LLM/Persistence/Identity/same-origin proxy tests |
| Docs | Service README、Backend/Overall/DevOps/AgentArts architecture、ADR-011 |

Implementation 前必须为所有将修改的 function/class 执行 GitNexus upstream impact
analysis，并报告 direct callers、affected processes 和 risk。重点包括：

- `get_model()` / `_resolve_provider()`
- `get_agent_handler()` / `AgentHandler._init_checkpointer()`
- `configure_logging()`
- Identity provider lookup 与 tool decorators
- FastAPI app import/startup flow

若任一项为 HIGH 或 CRITICAL，必须先向用户报告 blast radius，再进入编辑。完成
Implementation 后、commit 前必须运行 `gitnexus_detect_changes()`。

## 验收标准

### 用户体验

- [ ] 新用户只阅读 `.env.example` 即可发现全部 Service 可配置项及 Secret 指引
- [ ] README 的配置步骤不要求用户打开 `app/settings.py` 或 internal catalog
- [ ] 本地与生产使用相同 canonical variable names
- [ ] 根目录不再存在模糊的 `config.yaml`
- [ ] 错误信息指出应设置的 canonical variable 或 Identity provider

### 清理完整性

- [ ] `MODEL_API_KEY`、`MODEL_NAME`、`MODEL_URL` 在 active code、tests、deployment、
      README 和 current architecture 中均为零引用
- [ ] `CORS_ALLOWED_ORIGINS`、`CORSMiddleware`、默认 Origin list 和 CORS parsing
      在 active code、tests、deployment、README 和 current architecture 中均为零引用
- [ ] Service 不再从环境变量读取 LLM credential value
- [ ] `MAAS_API_KEY` / `DEEPSEEK_API_KEY` 不再作为 credential value env contract
- [ ] Service production code 不直接读取应用配置环境变量
- [ ] 不存在 `config.yaml` fallback、legacy alias 或 silent precedence
- [ ] `load_dotenv()` 和直接 `python-dotenv` dependency 已删除

### 正确性

- [ ] Settings、catalog 和跨字段约束在 startup fail fast
- [ ] Logging、Persistence、LLM 和 Identity 行为通过 typed configuration
- [ ] Web Chat 经 same-origin proxy 正常访问 Service，浏览器跨 Origin 直连不再属于
      supported deployment topology
- [ ] AgentArts Identity 是 credential value 的唯一来源
- [ ] 无 `.env` 的 production-like 环境可以启动
- [ ] legacy 变量即使设置也不生效
- [ ] 所有 Service Unit/Integration tests、Ruff 和 E2E tests 通过
- [ ] `gitnexus_detect_changes()` 只报告预期 symbols 和 execution flows
- [ ] current architecture 与实际实现一致

## Four-Question Gate

| Question | Answer | 论证 |
|----------|:------:|------|
| **Is it best practice?** | Yes | 对用户提供 Single Entry Point，对代码提供 typed Settings，对 Secret 提供独立安全边界；通过 fail-fast、Separation of Concerns 和删除重复 source of truth 降低错误率。 |
| **Is it industry standard?** | Yes | 环境变量作为 deployment contract、dotenv 用于本地、Pydantic Settings 负责类型校验、Secret Manager/Identity 保存 credential，是现代云原生 Python 服务的标准组合。 |
| **Is it conventional?** | Yes | 用户执行 `cp .env.example .env`，生产注入同名变量；内部 `settings.py` 和 resources catalog 对 FastAPI/Python 开发者清晰，但不暴露为第二用户入口。 |
| **Is it modern?** | Yes | 使用 Pydantic v2/pydantic-settings、immutable typed config、Identity-based secret delivery 和 fail-fast validation；主动删除 legacy fallback，而非长期背负兼容债务。 |

四个 gate 均为 **Yes**。

关键 trade-off：这是有意的 breaking change。旧 deployment 和测试必须同步迁移，
短期改动面大；换来的结果是用户只有一个配置入口，代码只有一个 Runtime source of
truth，Secret 只有一个可信来源。继续兼容旧变量会直接破坏该目标，因此不接受。

## 依赖与状态关系

- **Supersedes Refactor 3**：其 Provider schema、默认 Provider 和 legacy env 清理
  目标全部被本 issue 吸收；Refactor 3 不再单独实施。
- **与 Refactor 5 的边界**：本 issue 提供 validated Provider capabilities，
  Refactor 5 未来实现动态选择和 weight。
- **与 Refactor 8 的边界**：本 issue 确立 Secret 只能来自 AgentArts Identity；
  credential caching 是否需要、如何缓存仍由 Refactor 8 基于 profiling 决定。
- **历史依据**：
  [Bug 5](../../../bugs/resolved/bug-5-env-merge-prevents-key-removal-in-e2e-tests/issue.md)
  已证明全局 `load_dotenv()` 会污染 pytest collection。

## 参考

- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [FastAPI Settings and Environment Variables](https://fastapi.tiangolo.com/advanced/settings/)
- [The Twelve-Factor App: Config](https://12factor.net/config)
- [`backend_architecture.md`](../../../../architecture/backend_architecture.md)
- [`overall_architecture.md`](../../../../architecture/overall_architecture.md)
