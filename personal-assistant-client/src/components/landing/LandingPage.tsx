import { useMsal } from "@azure/msal-react";
import { loginRequest } from "@/lib/auth";
import { Calendar, Mail, NotebookPen, ListTodo } from "lucide-react";
import { GlobalNav } from "./GlobalNav";
import { LandingHero } from "./LandingHero";
import { CapabilityGrid } from "./CapabilityGrid";
import { FeatureTile } from "./FeatureTile";
import { ClosingCTA } from "./ClosingCTA";
import { LandingFooter } from "./LandingFooter";

export default function LandingPage() {
  const { instance } = useMsal();
  const handleLogin = () => instance.loginRedirect(loginRequest);

  return (
    <div className="landing-page">
      <GlobalNav onLogin={handleLogin} />
      <LandingHero
        headline="Personal Assistant"
        tagline="您的 AI 助手，用自然语言管理日程、邮件、笔记和任务"
        primaryCta={{ label: "开始对话", onClick: handleLogin }}
        secondaryCta={{ label: "了解更多", onClick: handleLogin }}
      />
      <CapabilityGrid
        headline="核心能力"
        cards={[
          {
            icon: Calendar,
            title: "日程管理",
            description: "自然语言创建、查询和修改日程，智能冲突检测与提醒。",
          },
          {
            icon: Mail,
            title: "邮件处理",
            description: "帮您撰写、回复和整理邮件，自动分类与优先级排序。",
          },
          {
            icon: NotebookPen,
            title: "笔记记录",
            description: "快速记录笔记，智能关联上下文，随时检索和回顾。",
          },
          {
            icon: ListTodo,
            title: "任务管理",
            description: "创建和跟踪任务，设定截止日期，自动提醒和状态更新。",
          },
        ]}
      />
      <FeatureTile
        variant="dark"
        headline="自然语言交互"
        description="无需复杂的操作界面，只需像和真人助手对话一样，用自然语言告诉 Personal Assistant 您的需求。支持多轮对话，自动理解上下文，让工具隐于无形。"
        cta={{ label: "了解更多", onClick: handleLogin }}
      />
      <FeatureTile
        variant="light"
        headline="跨渠道无缝衔接"
        description="无论您是通过 Web Chat 网页端、飞书消息还是 OfficeClaw 桌面客户端，Personal Assistant 都能保持一致的对话体验，所有渠道共享同一份记忆和偏好。"
        cta={{ label: "了解更多", onClick: handleLogin }}
      />
      <FeatureTile
        variant="parchment"
        headline="智能 Memory 与上下文感知"
        description="Personal Assistant 会记住您的偏好、习惯和重要信息。越用越懂您，每一次对话都在上一次的基础上变得更加智能和个性化。"
      />
      <ClosingCTA cta={{ label: "立即开始", onClick: handleLogin }} />
      <LandingFooter />
    </div>
  );
}
