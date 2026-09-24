# ADR-006: 基础设施即代码（IaC）工具选型 — OpenTofu + HCL

> 状态：Accepted | 日期：2026-06-03 | 修订：2026-06-09

---

## 背景

Personal Assistant 涉及两类基础设施资源：

| 层 | 资源 | 管理工具 |
|------|------|----------|
| Agent 运行时层 | Runtime 容器、Memory Space、Identity Provider、网络模式、认证配置 | `agentarts_config.yaml` |
| 华为云基础资源层 | OBS、RDS、EIP、IAM、CDN（未来需要时） | 需要选 |

**2026 年 6 月修订**：HashiCorp (IBM) 于 2025 年 12 月 10 日正式归档 CDKTF 仓库，停止所有维护和安全更新。原 ADR-006 选择 CDKTF (TypeScript)，现已不可持续。本次修订评估了三条替代路径：CDK Terrain（社区 fork）、Pulumi、OpenTofu + HCL，最终决定转向 **OpenTofu + 原生 HCL**。

## 决策

### Layer 1：AgentArts 层 → `agentarts_config.yaml`

AgentArts 平台原生提供的声明式配置文件。执行 `agentarts launch` 等同于 `terraform apply`。**不需要额外 IaC 工具。**

### Layer 3：华为云基础资源层 → **OpenTofu + HCL**

当项目需要 `agentarts_config.yaml` 管不到的华为云资源时，使用 OpenTofu + 原生 HCL 编写基础设施代码。

选择依据：

| 因素 | OpenTofu + HCL | CDK Terrain (cdktn) + TS | Pulumi |
|------|:---:|:---:|:---:|
| **治理/中立性** | ✅ Linux 基金会托管 | ⚠️ OCF 非营利（< 6 个月） | ⚠️ 商业公司（Pulumi Corp） |
| **行业标准** | ✅ Terraform HCL 是 IaC 事实标准 | ❌ CDKTF 从来不是主流 | ⚠️ 有用户群但不如 Terraform |
| **生态资料** | ✅ 99% Terraform 教程直接复用 | ❌ 几乎无独立社区 | ⚠️ 中等 |
| **架构复杂度** | ✅ 无编译层，报错直观 | ❌ TS→JSON→HCL 两层翻译 | ⚠️ 有状态管理层 |
| **类型安全** | ⚠️ `tofu plan` 阶段验证 | ✅ 编译期 | ✅ 编译期 |
| **学习成本** | ⚠️ 需学 HCL（1-2 天） | ✅ TypeScript 复用 | ⚠️ 需学 Pulumi 模型 |
| **当前项目匹配** | ✅ 资源极少（1 OBS Bucket） | ⚠️ CDK 优势无实际收益 | ❌ 杀鸡用牛刀 |
| **长期存活** | ✅ OpenTofu 在 Linux 基金下活跃 | 🔴 fork < 半年，前景不明 | ✅ 商业支持 |

## 拒绝的方案

### CDK Terrain (cdktn) — CDKTF 社区 fork

- 社区 fork 不到 6 个月（2026 年 1 月首版发布），ThoughtWorks Technology Radar 评级 "Assess"（不推荐采用）
- CDK-for-Terraform 方向本身已被市场否定——CDKTF 被归档的根本原因是"未能找到产品与市场契合点"（HashiCorp 官方声明）
- 引入 TypeScript → JSON → HCL 中间层的复杂度，但在当前项目规模（1 个 resource）下没有任何实际收益
- 长期存活风险真实：赞助商为小型 devtools 创业公司，非 CNCF/Linux 基金会级别

### Pulumi

- 功能强大但引入完整的状态管理引擎，对当前项目"一个 OBS Bucket"的规模是严重过度工程
- Python/TypeScript SDK 的抽象层同样存在"报错反向映射"问题
- 商业公司（Pulumi Corp）——虽然开源，但治理不中立

### CDKTF (原版)

- 已于 2025 年 12 月 10 日归档（Sunset + Archive），无安全补丁，不可继续使用

### RFS（华为云资源编排服务）

- 本质是托管的 Terraform 引擎，底层用同一个 `huaweicloud` provider
- 不能本地 `plan`，必须控制台操作，开发体验差
- `.tf` 文件可在 OpenTofu 和 RFS 之间无缝迁移，先用 OpenTofu 本地开发，如需上传控制台直接复用

### Terraform CLI (HashiCorp)

- 2023 年 HashiCorp 将 Terraform 从 MPL 切换为 BUSL（Business Source License），不再属于真正的开源
- OpenTofu 是 MPL 协议下 Terraform 的 Linux 基金会 fork，100% 兼容且真正开源

## 影响

### AgentArts 层

- 所有 AgentArts 配置集中在 `.agentarts_config.yaml`
- 部署命令：`agentarts launch`
- 不需要 Terraform 或 OpenTofu

### 华为云基础资源层

建立 `personal-assistant-infra/` 目录，与 AgentArts 层解耦：

```
personal-assistant-infra/
├── main.tf                # terraform {} + provider "huaweicloud" {}
├── obs.tf                 # OBS Bucket 资源（web chat 静态托管）
├── variables.tf           # 变量声明（region，Provider 凭据通过原生环境变量注入）
├── outputs.tf             # Stack outputs
├── terraform.tfvars       # 变量赋值（gitignored，不再用于 AK/SK）
├── .terraform.lock.hcl    # Provider 版本锁
├── .gitignore             # Terraform 排除规则
├── AGENTS.md              # 本目录专用 instructions
└── README.md              # 快速开始
```

典型 HCL 代码（等价于原 CDKTF TypeScript Stack）：

```hcl
# main.tf
terraform {
  required_providers {
    huaweicloud = {
      source  = "huaweicloud/huaweicloud"
      version = "~> 1.92"
    }
  }
}

provider "huaweicloud" {
  region     = var.region
  # 凭据通过 HW_ACCESS_KEY / HW_SECRET_KEY 原生环境变量注入（修订 2026-06-10）
}
```

```hcl
# obs.tf
resource "huaweicloud_obs_bucket" "web_chat" {
  bucket      = "personal-assistant-web-chat"
  acl         = "public-read"
  versioning  = true

  website {
    index_document = "index.html"
    error_document = "index.html"
  }
}
```

部署流程：

```bash
cd personal-assistant-infra
tofu init               # 初始化 provider
tofu validate           # 语法验证
tofu plan               # 查看变更计划
tofu apply              # 执行部署
```

### 与 agentarts 的关系

两者互不冲突，管不同层的资源：

```
.agentarts_config.yaml    → AgentArts 层（容器/认证/可观测）
infra/*.tf                → 华为云基础资源层（OBS/RDS/IAM）
```

### 从 CDKTF 迁移

- 删除所有 TypeScript 和 Node.js 相关文件（`main.ts`, `stacks/`, `package.json`, `tsconfig.json`, `jest.config.js`, `cdktf.json`）
- 删除 `.gen/`（provider bindings）和 `cdktf.out/`（输出目录）
- 删除 `node_modules/`
- HCL 重写（~35 行等价代码）
- 如果已部署过 OBS Bucket：`tofu import huaweicloud_obs_bucket.web_chat personal-assistant-web-chat`

## 参考

- [OpenTofu 官网](https://opentofu.org)
- [OpenTofu CLI 文档](https://opentofu.org/docs/cli/)
- [HuaweiCloud Provider (OpenTofu Registry)](https://search.opentofu.org/provider/opentofu/huaweicloud)
- [CDKTF Sunset Notice](https://developer.hashicorp.com/terraform/cdktf)
- [CDK Terrain 评估](https://cdktn.io) — 决定不采用
- [ThoughtWorks Technology Radar — CDK Terrain](https://www.thoughtworks.com/en-us/radar/tools/cdk-terrain) — Assess
- [Refactor 6: 从 CDKTF 迁移到 OpenTofu + HCL](../../issues/refactor/resolved/refactor-6-migrate-cdktf-to-opentofu-hcl/issue.md)
- `architecture/devops/cicd.md` §4 Layer 3 详细说明
