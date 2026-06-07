# ADR-011: 多 LLM Provider 可配置架构

> 状态：Accepted | 日期：2026-06-07

---

## 背景

ADR-005 确定了以华为云 MaaS 作为唯一 LLM 推理平台。该决策的核心驱动因素是：(1) 华为云技术栈展示，(2) 内网连通性和数据合规，(3) 模型广场多模型选择。

随着项目演进，出现了两个新需求：

1. **开发灵活性**：在家办公或无 VPN 时 MaaS 不可达，需要一个公网可达的 provider 作为开发备选
2. **多 Provider 共存**：不同任务可能适合不同 provider（如 MaaS 用于生产、DeepSeek 官方用于低成本长尾任务）。用户希望按需切换，而非硬编码单一 provider

两个 provider 均使用 OpenAI-compatible API，切换成本极低——只需换 `base_url` 和 `api_key`。

## 决策

**引入多 LLM Provider 可配置架构。Provider 通过 `config.yaml` 声明式配置，运行时按名称选取，支持默认 provider 和运行时切换。**

### 配置结构

```yaml
# config.yaml
llm:
  default: maas
  providers:
    maas:
      base_url: https://api.modelarts-maas.com/openai/v1
      api_key_env: MAAS_API_KEY
      model: deepseek-v4-pro
    deepseek:
      base_url: https://api.deepseek.com
      api_key_env: DEEPSEEK_API_KEY
      model: deepseek-chat
```

### 设计原则

| 维度 | 选择 | 说明 |
|------|------|------|
| **配置载体** | `config.yaml` + env var 引用 | YAML 声明 provider 元数据，env var 承载密钥。12-factor 兼容 |
| **密钥管理** | `api_key_env` 间接引用 | 配置文件中不留明文密钥，通过环境变量名引用 |
| **默认 Provider** | `llm.default` 字段 | 明确默认值，避免隐式 fallback |
| **运行时切换** | `provider` 参数传入 `get_model()` | Agent 代码可通过参数指定 provider，不改配置即可切换 |
| **Provider 抽象** | 数据对象，非类继承 | 两个 provider 都是 OpenAI-compatible，同一个 `init_chat_model()` 调用，不需要多态 |

### 选择依据

| 因素 | 多 Provider（本方案） | 单 Provider（现状） |
|------|----------------------|---------------------|
| **开发灵活性** | VPN 断了切 DeepSeek 官方 | VPN 断了无法开发 |
| **成本弹性** | 简单任务走便宜 provider | 所有任务一个价格 |
| **合规** | 生产仍走 MaaS，数据不出华为云 | ✅ |
| **展示价值** | 展示多 provider 管理和动态路由 | 展示 MaaS 平台 |
| **复杂度** | +1 配置文件 + 配置加载模块 | 零 |
| **维护成本** | 低（同协议，无适配层） | 零 |

## 拒绝的方案

### 单 Provider + 手动改环境变量切换

即保持现状的 `MODEL_URL` / `MODEL_API_KEY` / `MODEL_NAME` 三个环境变量，切换时手动改。

- **拒绝理由**：不支持多 provider 共存。每次切换需要改 env 并重启服务，不适合产线场景。

### Provider 继承体系（AbstractLLMProvider → MaaSProvider / DeepSeekProvider）

引入类继承和多态，每个 provider 实现自己的 `get_model()` 方法。

- **拒绝理由**：过度设计。两个 provider 都是 OpenAI-compatible，用同一个 `init_chat_model()` 即可，不需要多态。真遇到非 OpenAI 协议的 provider 时再引入适配层。

### 每个 Provider 独立 `init_chat_model()`

不抽象 provider 层，在调用处分别写两套 `init_chat_model()`。

- **拒绝理由**：代码重复，切换逻辑散落各处。`config.yaml` 的集中配置更明确、更易审计。

## 影响

### 新增文件

- `config.yaml`：LLM provider 配置（项目根目录）
- `app/llm_config.py`：配置加载模块，读取 `config.yaml` + 环境变量，暴露 `get_model(provider: str = None) -> BaseChatModel`

### 修改文件

| 文件 | 改动 |
|------|------|
| `app/agent_handler.py` | `init_chat_model()` 改为 `llm_config.get_model()` |
| `agentarts_config.yaml` | 新增 `DEEPSEEK_API_KEY` env var；`MODEL_URL` / `MODEL_API_KEY` / `MODEL_NAME` 保持兼容性（作为 `maas` provider 的 fallback），逐步废弃 |
| `architecture/overall_architecture.md` | 技术选型表 LLM 行更新 |
| `architecture/backend_architecture.md` | Agent 处理逻辑代码示例更新 |
| `architecture/devops/local-development.md` | 环境变量一览增加 DeepSeek 配置 |
| `specs/overall_specifications.md` | 新增 LLM Provider 小节 |
| `specs/dictionary.md` | 新增 LLM Provider 术语 |

### 废弃（向后兼容保留）

- `MODEL_URL` / `MODEL_API_KEY` / `MODEL_NAME` 三个单一 provider 环境变量。当 `config.yaml` 未配置 `maas` provider 时，从这三个 env var 读取作为 fallback。后续版本移除。

### 不修改

- AgentArts 部署流程（`agentarts launch`）
- Dockerfile
- Agent 编排逻辑（deepagents）
- 各路由和工具

## 参考

- [ADR-005](ADR-005-maas-llm-platform.md) — 华为云 MaaS 作为 LLM 推理平台（本 ADR 对其 amend）
- [DeepSeek API 文档](https://api-docs.deepseek.com/)
- [12-Factor App: Config](https://12factor.net/config)
- [langchain-openai `init_chat_model()`](https://python.langchain.com/docs/integrations/chat/)
