import { useReportProgressStore } from "@/stores/report-progress-store";
import type {
  ReportProgressPayload,
  ReportProgressSource,
  ReportProgressStage,
} from "@/types/chat";
import {
  AlertCircleIcon,
  CalendarDaysIcon,
  CheckCircle2Icon,
  CircleMinusIcon,
  FileTextIcon,
  GitBranchIcon,
  LoaderCircleIcon,
  MailIcon,
} from "lucide-react";
import type { FC } from "react";

export interface ReportProgressCardProps {
  messageId: string;
}

const SOURCE_ORDER: ReportProgressSource[] = ["github", "email", "calendar"];

const SOURCE_LABELS: Record<ReportProgressSource, string> = {
  github: "GitHub",
  email: "邮件",
  calendar: "日历",
};

const STAGE_LABELS: Record<ReportProgressStage, string> = {
  preparing: "准备数据源",
  github_context: "读取账号和仓库范围",
  activity_search: "检索 GitHub 活动",
  activity_detail: "补充 GitHub 活动详情",
  email_collection: "采集邮件",
  calendar_collection: "采集日历",
  rendering: "整理 Markdown 报告",
};

function SourceIcon({ source }: { source?: ReportProgressSource }) {
  const className = "size-4 shrink-0 text-muted-foreground";
  if (source === "github") return <GitBranchIcon className={className} />;
  if (source === "email") return <MailIcon className={className} />;
  if (source === "calendar") return <CalendarDaysIcon className={className} />;
  return <FileTextIcon className={className} />;
}

function StatusIcon({ progress }: { progress: ReportProgressPayload }) {
  if (progress.status === "complete") {
    return <CheckCircle2Icon className="size-4 shrink-0 text-green-600" />;
  }
  if (progress.status === "failed") {
    return <AlertCircleIcon className="text-destructive size-4 shrink-0" />;
  }
  if (progress.status === "skipped") {
    return <CircleMinusIcon className="size-4 shrink-0 text-muted-foreground" />;
  }
  return (
    <LoaderCircleIcon className="text-primary size-4 shrink-0 animate-spin" />
  );
}

function progressDetail(progress: ReportProgressPayload): string {
  if (progress.status === "failed") return "暂不可用";
  if (progress.status === "skipped") return "已跳过";
  if (
    typeof progress.current === "number" &&
    typeof progress.total === "number" &&
    progress.total > 0
  ) {
    return `${Math.min(progress.current, progress.total)} / ${progress.total}`;
  }
  if (typeof progress.discovered === "number") {
    if (progress.stage === "github_context") {
      return `${progress.discovered} 个仓库`;
    }
    return `已发现 ${progress.discovered} 项`;
  }
  return progress.status === "complete" ? "已完成" : "进行中";
}

function ProgressRow({ progress }: { progress: ReportProgressPayload }) {
  const sourceLabel = progress.source
    ? SOURCE_LABELS[progress.source]
    : "报告";
  return (
    <li
      data-slot="report-progress-row"
      data-source={progress.source ?? "report"}
      data-stage={progress.stage}
      data-status={progress.status}
      className="grid min-w-0 grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-2 py-1.5"
    >
      <SourceIcon source={progress.source} />
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{sourceLabel}</p>
        <p className="truncate text-xs text-muted-foreground">
          {STAGE_LABELS[progress.stage]}
        </p>
      </div>
      <div className="flex min-w-16 shrink-0 items-center justify-end gap-1.5 text-xs text-muted-foreground">
        <StatusIcon progress={progress} />
        <span className="whitespace-nowrap">{progressDetail(progress)}</span>
      </div>
    </li>
  );
}

export const ReportProgressCard: FC<ReportProgressCardProps> = ({
  messageId,
}) => {
  const entry = useReportProgressStore(
    (state) => state.progressByMessageId[messageId],
  );
  if (!entry || entry.terminal) return null;

  const sourceProgress = SOURCE_ORDER.flatMap((source) => {
    const progress = entry.sources[source];
    return progress ? [progress] : [];
  });
  const visibleProgress: ReportProgressPayload[] = [];
  if (
    entry.global &&
    (entry.global.status === "running" ||
      entry.global.stage === "rendering" ||
      sourceProgress.length === 0)
  ) {
    visibleProgress.push(entry.global);
  }
  visibleProgress.push(...sourceProgress);
  const isBusy = visibleProgress.some(
    (progress) => progress.status === "running",
  );

  return (
    <div
      data-slot="report-progress-panel"
      data-sequence={entry.sequence}
      role="status"
      aria-live="polite"
      aria-busy={isBusy}
      className="my-4 w-full min-w-0 rounded-lg border border-border bg-muted/40 p-3"
    >
      <div className="flex min-w-0 items-center gap-2">
        {isBusy ? (
          <LoaderCircleIcon className="text-primary size-4 shrink-0 animate-spin" />
        ) : (
          <CheckCircle2Icon className="size-4 shrink-0 text-green-600" />
        )}
        <p className="min-w-0 text-sm font-semibold">正在生成报告</p>
      </div>
      <ul className="mt-2 divide-y divide-border/70">
        {visibleProgress.map((progress) => (
          <ProgressRow
            key={`${progress.source ?? "report"}:${progress.stage}`}
            progress={progress}
          />
        ))}
      </ul>
    </div>
  );
};
