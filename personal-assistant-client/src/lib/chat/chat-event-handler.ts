import { useAuthCardStore } from "@/stores/auth-card-store";
import { useReportDownloadStore } from "@/stores/report-download-store";
import { useReportProgressStore } from "@/stores/report-progress-store";
import type {
  ReportProgressPayload,
  ReportProgressSource,
  ReportProgressStage,
  ReportProgressStatus,
  SSEEvent,
} from "@/types/chat";

const REPORT_PROGRESS_SOURCES = new Set<ReportProgressSource>([
  "github",
  "email",
  "calendar",
]);
const REPORT_PROGRESS_STAGES = new Set<ReportProgressStage>([
  "preparing",
  "github_context",
  "activity_search",
  "activity_detail",
  "email_collection",
  "calendar_collection",
  "rendering",
]);
const REPORT_PROGRESS_STATUSES = new Set<ReportProgressStatus>([
  "running",
  "complete",
  "failed",
  "skipped",
]);

interface ChatEventContext {
  assistantMessageId: string;
  fullText: string;
}

interface ChatEventResult {
  fullText: string;
  contentUpdates: string[];
  done: boolean;
}

function reportProgressPayload(event: SSEEvent): ReportProgressPayload | null {
  const isProgressEvent =
    event.report_progress === true || event.type === "report_progress";
  if (
    !isProgressEvent ||
    typeof event.sequence !== "number" ||
    !Number.isInteger(event.sequence) ||
    typeof event.stage !== "string" ||
    !REPORT_PROGRESS_STAGES.has(event.stage) ||
    typeof event.status !== "string" ||
    !REPORT_PROGRESS_STATUSES.has(event.status) ||
    (event.source !== undefined && !REPORT_PROGRESS_SOURCES.has(event.source))
  ) {
    return null;
  }
  return {
    sequence: event.sequence,
    source: event.source,
    stage: event.stage,
    status: event.status,
    current: event.current,
    total: event.total,
    discovered: event.discovered,
  };
}

export function handleChatEvent(
  event: SSEEvent,
  context: ChatEventContext,
): ChatEventResult {
  if (event.error) {
    useReportProgressStore
      .getState()
      .finishProgress(context.assistantMessageId);
    throw new Error(event.error);
  }

  let fullText = context.fullText;
  const contentUpdates: string[] = [];

  if (typeof event.token === "string") {
    fullText += event.token;
    contentUpdates.push(fullText);
  }

  const systemMessage =
    typeof event.system_message === "string" ? event.system_message : "";
  const isAuthEvent =
    event.auth_required === true ||
    event.auth_complete === true ||
    event.auth_failed === true;
  const isReportProgressEvent =
    event.report_progress === true || event.type === "report_progress";
  const isReportReadyEvent =
    event.report_ready === true || event.type === "report_ready";

  const progress = reportProgressPayload(event);
  if (progress) {
    useReportProgressStore
      .getState()
      .setProgress(context.assistantMessageId, progress);
  }

  if (
    event.auth_required &&
    event.auth_url &&
    event.provider &&
    systemMessage.trim()
  ) {
    useAuthCardStore.getState().setAuth(
      context.assistantMessageId,
      event.provider,
      event.auth_url,
      systemMessage,
      event.oauth2_state,
    );
  }

  if (event.auth_complete && event.provider) {
    useAuthCardStore
      .getState()
      .setAuthComplete(
        context.assistantMessageId,
        event.provider,
        systemMessage || undefined,
        event.oauth2_state,
      );
  }

  if (event.auth_failed && event.provider) {
    useAuthCardStore
      .getState()
      .setAuthFailed(
        context.assistantMessageId,
        event.provider,
        systemMessage || undefined,
        event.oauth2_state,
      );
  }

  if (isReportReadyEvent) {
    useReportProgressStore
      .getState()
      .finishProgress(context.assistantMessageId, event.sequence, {
        createIfMissing: true,
      });
  }

  if (
    isReportReadyEvent &&
    event.report_format === "markdown" &&
    typeof event.report_content === "string" &&
    event.report_content.trim()
  ) {
    useReportDownloadStore.getState().setReport(context.assistantMessageId, {
      content: event.report_content,
      filename:
        typeof event.report_filename === "string" &&
        event.report_filename.trim()
          ? event.report_filename
          : "report.md",
      format: "markdown",
    });
  }

  if (
    !isAuthEvent &&
    !isReportProgressEvent &&
    !isReportReadyEvent &&
    systemMessage.trim()
  ) {
    fullText += systemMessage;
    contentUpdates.push(fullText);
  }

  if (event.done === true) {
    useReportProgressStore
      .getState()
      .finishProgress(context.assistantMessageId);
  }

  return {
    fullText,
    contentUpdates,
    done: event.done === true,
  };
}
