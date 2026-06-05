# DevOps — Coding Agent 最佳实践

本文档面向 Paperclip 的 CEO Agent，定义 Personal Assistant 项目所需的 coding agent 团队结构，以及每个角色的职责划分和管辖范围。

## 角色

### 1. CTO
- 运行载体：Hermes Agent
- 负责所有 manager 相关任务的派发与最终验收

instructions：
  1. 创建 sub issue 分配给 Design Manager
  2. Design Manager 完成后，创建 sub issue 分配给 Backend Dev Manager
  3. Backend Dev Manager 完成后，创建 sub issue 分配给 Frontend Dev Manager
  4. 任一步骤验收不通过时，重新按照上面的步骤顺序发起下一轮迭代，直至通过

### 2. Design Manager
- 运行载体：Hermes Agent
负责架构设计相关任务的派发与验收。

instructions：
1. 创建 sub issue 分配给 Architect，完成架构设计，产出落在 `personal-assistant-meta` 目录下
2. Architect 完成后，创建 sub issue 分配给 Developer 进行 review
3. 验收不通过时，重新按照上面的步骤顺序发起下一轮迭代，直至通过

### 3. Backend Dev Manager
- 运行载体：Hermes Agent
负责后端开发任务的派发与验收。

instructions：
1. 创建 sub issue 分配给 Developer，完成后端代码开发，产出落在 `personal-assistant-service` 目录下
2. Developer 完成后，创建 sub issue 分配给 QA 进行测试
3. 验收不通过时，重新按照上面的步骤顺序发起下一轮迭代，直至通过

### 4. Frontend Dev Manager
- 运行载体：Hermes Agent
负责前端开发任务的派发与验收。

instructions：
1. 创建 sub issue 分配给 Developer，完成前端代码开发，产出落在 `personal-assistant-client` 目录下
2. Developer 完成后，创建 sub issue 分配给 QA 进行测试
3. 验收不通过时，重新按照上面的步骤顺序发起下一轮迭代，直至通过

### 5. Architect
- 运行载体：Hermes Agent
- instructions: 专职架构设计

### 6. Developer
- 运行载体：OpenCode
- instructions: 专职代码开发

### 7. QA
- 运行载体：OpenCode
- instructions: 专职代码测试

## 工作流程理念

本质上是多层嵌套的控制回路（control loop）：

- 每一个 manager 都是一个独立的控制回路，不断循环重复，直至验收通过
- 验收不通过 → 重新走一遍自己管辖的步骤 → 再次验收 → 重复，直到通过
## Control Loop 全景图

```mermaid
flowchart TD
    subgraph CTO["CTO Issue (Hermes Agent)"]
        direction TB

        subgraph DM["sub-issue: Design Manager (Hermes Agent)"]
            direction LR
            ARCH["sub-issue: Architect<br/>Hermes<br/>产出: meta/"]
            DM_DEV["sub-issue: Developer<br/>OpenCode<br/>Review"]
            ARCH --> DM_DEV
        end

        subgraph BDM["sub-issue: Backend Dev Manager (Hermes Agent)"]
            direction LR
            BDM_DEV["sub-issue: Developer<br/>OpenCode<br/>产出: service/"]
            BDM_QA["sub-issue: QA<br/>OpenCode<br/>测试"]
            BDM_DEV --> BDM_QA
        end

        subgraph FDM["sub-issue: Frontend Dev Manager (Hermes Agent)"]
            direction LR
            FDM_DEV["sub-issue: Developer<br/>OpenCode<br/>产出: client/"]
            FDM_QA["sub-issue: QA<br/>OpenCode<br/>测试"]
            FDM_DEV --> FDM_QA
        end
    end

    DM --> BDM
    BDM --> FDM
```

