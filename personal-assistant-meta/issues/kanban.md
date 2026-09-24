# Issues Kanban

本看板仅展示尚未归档的 issue。位于 `resolved/`、`canceled/` 或 `archived/`
目录中的 issue，以及显式标记为 `resolved` 或 `canceled` 的 issue，均不纳入看板。

看板优先采用 issue 文件中的 `status`；存在 `blocked_by` 时归入 Blocked；缺少标准
`status` 时，以 issue 正文和同类 README 中的状态说明为准。

图类型：**Kanban Diagram（看板图）**。用于按当前工作状态汇总尚未归档的 Feature、Bug、Chore 和 Refactor。

```mermaid
kanban
  backlog[Backlog]
    bug11["AgentArts 平台级缺陷与限制汇总"]@{ ticket: 'BUG-11' }
    chore2["SWR 镜像命名整理"]@{ ticket: 'CHORE-2' }
    feature2["Memory 集成"]@{ ticket: 'FEATURE-2' }
    feature3["OfficeClaw 渠道"]@{ ticket: 'FEATURE-3' }
    feature5["飞书渠道"]@{ ticket: 'FEATURE-5' }
    feature6["Outbound User Federation (GitHub Tool)"]@{ ticket: 'FEATURE-6' }
    feature7["Outbound M2M (内部 API Tool)"]@{ ticket: 'FEATURE-7' }
    feature8["Outbound STS (云资源 Tool)"]@{ ticket: 'FEATURE-8' }
    feature9["部署上线与全链路可观测"]@{ ticket: 'FEATURE-9' }
    feature17["GitHub MCP Activity Data Source and Tools"]@{ ticket: 'FEATURE-17' }
    refactor5["LLM Provider 动态路由选择"]@{ ticket: 'REFACTOR-5' }
    refactor14["移除 Cloudflare /invocations/* catch-all proxy"]@{ ticket: 'REFACTOR-14' }

  blocked[Blocked]
    feature16["Inbound Auth 切换到 Microsoft Entra common"]@{ ticket: 'FEATURE-16' }

  open[Open]
    bug27["Feature 18 在线上提前断流并使 Conversation 保持 busy"]@{ ticket: 'BUG-27' }

  inProgress[In Progress]
    bug26["Cancel 失败后 Conversation 无法恢复发送"]@{ ticket: 'BUG-26' }
    chore7["测试体系治理与 E2E 分层落地"]@{ ticket: 'CHORE-7' }
    feature18["Report Root Capability"]@{ ticket: 'FEATURE-18' }

  implemented[Implemented / Validation]
    bug20["OAuth2 callback state nonce replay protection 未跨实例生效"]@{ ticket: 'BUG-20' }
    bug23["中断聊天后 Conversation 仍保持 busy"]@{ ticket: 'BUG-23' }
    bug24["Feature 14 重构导致 PostgreSQL Checkpointer 自愈回归"]@{ ticket: 'BUG-24' }
    bug25["首次聊天创建的 Conversation 未出现在 Sidebar"]@{ ticket: 'BUG-25' }
    feature14["Web Chat 多 Conversation 与 Runtime 提前唤醒"]@{ ticket: 'FEATURE-14' }
```
