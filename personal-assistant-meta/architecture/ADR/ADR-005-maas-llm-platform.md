# ADR-005: 华为云 MaaS 作为 LLM 推理平台

> 状态：Accepted (Amended by [ADR-011](ADR-011-multi-llm-provider.md)) | 日期：2026-06-03 | 修订：2026-06-07

> **2026-06-07 修订**：ADR-011 引入多 LLM Provider 架构。MaaS 仍为默认/生产 provider，DeepSeek 官方作为备选 provider 共存。本 ADR 的"拒绝 DeepSeek 官方 API"改为"拒绝 DeepSeek 官方 API 作为**唯一** provider"。

---

## 背景

Personal Assistant Agent 需要一个 LLM 推理服务来驱动 Agent 推理循环。核心需求：

- 支持 Function Calling / Tool Use（Agent 的根基能力）
- 中文能力强（面向中国用户）
- 通过华为云内部网络可访问（低延迟、无 GFW 干扰）
- OpenAI-compatible API（降低代码耦合度）

有两种路径：直接对接模型厂商 API（DeepSeek 官方 / 硅基流动等），或使用云平台托管服务。

## 决策

**使用华为云 MaaS（ModelArts as a Service）作为 LLM 推理平台。**

MaaS 是华为云的大模型即服务平台，提供模型广场、一键部署、API 调用和 Tokens 计费。这是一个**平台级决策**，模型只是平台上的一个可替换参数。

选择依据：

| 因素 | MaaS | 模型厂商直连 |
|------|------|-------------|
| **华为云生态** | 同一账号体系，内网互通 | 跨公网调用 |
| **网络延迟** | 内网直连，毫秒级 | 经过 GFW，不稳定 |
| **模型选择** | 模型广场多模型（DeepSeek / Qwen / GLM 等） | 单一厂商 |
| **计费** | 华为云统一账单 | 多厂商分别结算 |
| **合规** | 数据不出华为云 | 数据流向第三方 |
| **展示价值** | 华为云完整 AI 技术栈 | 仅展示模型使用 |

### 当前模型选择

**默认模型：DeepSeek-V4-Pro**（1.6T 参数 / 49B 激活，1M 上下文）。

选择依据：
- 2026-04-24 发布，华为云首发适配
- Agent 能力在开源模型中领先（Terminal Bench 2.0: 67.9%）
- 支持 Non-think / Think High / Think Max 三种推理强度，适应不同任务

备选模型（均在 MaaS 模型广场可用）：

| 备选 | 切换触发条件 |
|------|-------------|
| DeepSeek-V4-Flash | 成本敏感场景，284B 参数，API 已上线 |
| Qwen3-32B / Qwen3-235B | DeepSeek 服务中断时的首选替代 |
| 华为云盘古 Ultra MoE | 盘古 Function Calling 成熟后考虑迁移 |

## 拒绝的方案

### DeepSeek 官方 API 作为唯一 provider

> **Amended by ADR-011**：DeepSeek 官方 API 已作为**备选 provider** 纳入多 provider 架构，供无 VPN 的开发场景和低成本任务使用。以下原始拒绝理由适用于"作为唯一 provider"的决策。

- 需要经过公网，GFW 环境下不稳定
- 数据流向第三方，合规风险
- 不能展示华为云 MaaS 的平台能力

### 硅基流动 / 其他第三方平台

- 额外引入第三方依赖
- 与"华为云技术栈展示"定位矛盾

### vLLM 自建推理

- 运维成本高（GPU 实例管理、模型更新、扩缩容）
- MaaS Serverless 模式更符合 AgentArts 平台定位

## 影响

> 本 ADR 已被 [ADR-011](ADR-011-multi-llm-provider.md) amend——引入多 provider 架构后，MaaS 降级为"默认 provider"，不再独占 LLM 调用。

- MaaS API 端点：`https://api.modelarts-maas.com/openai/v1`
- 使用 `langchain-openai` 的 `ChatOpenAI` 调用，OpenAI 兼容协议
- Provider 配置通过 `config.yaml` 的 `llm.providers.maas` 段管理，API Key 通过 `MAAS_API_KEY` 环境变量注入
- MaaS 模型会持续更新（V3.2 → V4 已完成），ADR 不锁定具体版本

## 参考

- [华为云 MaaS 产品页](https://www.huaweicloud.com/product/modelarts/studio.html)
- [DeepSeek-V4 华为云首发适配](https://www.qbitai.com/2026/04/406791.html)（2026-04-24）
- 华为云 MaaS 模型广场（控制台可查看当前可用模型列表）
