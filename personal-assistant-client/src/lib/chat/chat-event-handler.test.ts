import { beforeEach, describe, expect, it } from "vitest";
import { useAuthCardStore } from "@/stores/auth-card-store";
import { useReportDownloadStore } from "@/stores/report-download-store";
import { useReportProgressStore } from "@/stores/report-progress-store";
import { handleChatEvent } from "./chat-event-handler";

describe("handleChatEvent report_ready", () => {
  beforeEach(() => {
    useAuthCardStore.getState().clearAuth();
    useReportDownloadStore.getState().clearReport();
    useReportProgressStore.getState().clearProgress();
  });

  it("stores structured progress without adding it to assistant text", () => {
    const context = {
      assistantMessageId: "assistant-progress",
      fullText: "报告请求已接收",
    };
    const result = handleChatEvent(
      {
        type: "report_progress",
        report_progress: true,
        sequence: 3,
        source: "github",
        stage: "activity_search",
        status: "running",
        current: 2,
        discovered: 37,
        system_message: "这段进度不应进入正文",
      },
      context,
    );

    expect(result).toEqual({
      fullText: "报告请求已接收",
      contentUpdates: [],
      done: false,
    });
    expect(
      useReportProgressStore.getState().progressByMessageId[
        "assistant-progress"
      ].sources.github,
    ).toMatchObject({
      sequence: 3,
      stage: "activity_search",
      discovered: 37,
    });

    handleChatEvent(
      {
        type: "report_progress",
        report_progress: true,
        sequence: 2,
        source: "github",
        stage: "activity_search",
        status: "running",
        discovered: 0,
      },
      context,
    );
    expect(
      useReportProgressStore.getState().progressByMessageId[
        "assistant-progress"
      ].sources.github?.discovered,
    ).toBe(37);
  });

  it("stores the original Markdown for the matching assistant message", () => {
    const result = handleChatEvent(
      {
        type: "report_ready",
        report_ready: true,
        report_format: "markdown",
        report_filename: "日报-2024-02-14.md",
        report_content: "# 日报\n\n- 时间范围：2024-02-14",
        report_type: "daily",
      },
      { assistantMessageId: "assistant-report-1", fullText: "生成中" },
    );

    expect(result).toEqual({
      fullText: "生成中",
      contentUpdates: [],
      done: false,
    });
    expect(
      useReportDownloadStore.getState().reportsByMessageId[
        "assistant-report-1"
      ],
    ).toEqual({
      content: "# 日报\n\n- 时间范围：2024-02-14",
      filename: "日报-2024-02-14.md",
      format: "markdown",
    });
    expect(
      useReportProgressStore.getState().progressByMessageId[
        "assistant-report-1"
      ],
    ).toMatchObject({ sequence: 0, terminal: true });
  });

  it("does not create progress state when an ordinary message finishes", () => {
    handleChatEvent(
      { done: true },
      { assistantMessageId: "ordinary-message", fullText: "完成" },
    );

    expect(
      useReportProgressStore.getState().progressByMessageId,
    ).not.toHaveProperty("ordinary-message");
  });

  it("ignores incomplete report events without changing OAuth state", () => {
    useAuthCardStore.getState().setAuth(
      "auth-message",
      "github-provider",
      "https://github.example/authorize",
      "请完成 GitHub 授权",
    );

    handleChatEvent(
      {
        report_ready: true,
        report_format: "markdown",
        report_filename: "empty.md",
        report_content: "",
      },
      { assistantMessageId: "assistant-report-2", fullText: "" },
    );

    expect(useReportDownloadStore.getState().reportsByMessageId).toEqual({});
    expect(
      useAuthCardStore.getState().cardsByMessageId["auth-message"]?.[0]
        ?.message,
    ).toBe("请完成 GitHub 授权");
  });

  it("keeps sequential provider cards when report_ready arrives", () => {
    const context = {
      assistantMessageId: "assistant-report-auth",
      fullText: "",
    };
    const authEvents = [
      {
        provider: "github-provider",
        auth_url: "https://auth.example.com/github",
        system_message: "请完成 GitHub 授权",
      },
      {
        provider: "m365-email-provider",
        auth_url: "https://auth.example.com/email",
        system_message: "请完成邮件授权",
      },
      {
        provider: "m365-calendar-provider",
        auth_url: "https://auth.example.com/calendar",
        oauth2_state: "calendar-state",
        system_message: "请完成日历授权",
      },
    ];

    for (const event of authEvents) {
      handleChatEvent({ ...event, auth_required: true }, context);
      handleChatEvent(
        {
          provider: event.provider,
          oauth2_state: event.oauth2_state,
          system_message: `${event.provider} 授权已完成`,
          auth_complete: true,
        },
        context,
      );
    }

    handleChatEvent(
      {
        type: "report_progress",
        report_progress: true,
        sequence: 1,
        source: "github",
        stage: "activity_detail",
        status: "running",
        current: 18,
        total: 37,
      },
      context,
    );

    handleChatEvent(
      {
        type: "report_ready",
        report_ready: true,
        report_format: "markdown",
        report_filename: "日报.md",
        report_content: "# 日报",
      },
      context,
    );

    expect(
      useAuthCardStore.getState().cardsByMessageId["assistant-report-auth"],
    ).toMatchObject([
      { provider: "github-provider", authComplete: true },
      { provider: "m365-email-provider", authComplete: true },
      {
        provider: "m365-calendar-provider",
        oauth2State: "calendar-state",
        authComplete: true,
      },
    ]);
    expect(
      useReportProgressStore.getState().progressByMessageId[
        "assistant-report-auth"
      ],
    ).toMatchObject({ terminal: true, sequence: 1 });
  });

  it("updates auth statuses only on the originating message", () => {
    const provider = "github-provider";
    const olderContext = {
      assistantMessageId: "assistant-auth-older",
      fullText: "",
    };
    const newerContext = {
      assistantMessageId: "assistant-auth-newer",
      fullText: "",
    };

    handleChatEvent(
      {
        auth_required: true,
        auth_url: "https://auth.example.com/github/older",
        provider,
        system_message: "请完成旧消息的 GitHub 授权",
      },
      olderContext,
    );
    handleChatEvent(
      {
        auth_required: true,
        auth_url: "https://auth.example.com/github/newer",
        provider,
        system_message: "请完成新消息的 GitHub 授权",
      },
      newerContext,
    );

    handleChatEvent(
      {
        auth_complete: true,
        provider,
        system_message: "旧消息的 GitHub 授权已完成",
      },
      olderContext,
    );

    const cards = useAuthCardStore.getState().cardsByMessageId;
    expect(cards[olderContext.assistantMessageId]?.[0]).toMatchObject({
      authComplete: true,
      message: "旧消息的 GitHub 授权已完成",
    });
    expect(cards[newerContext.assistantMessageId]?.[0]).toMatchObject({
      authComplete: false,
      authFailed: false,
      message: "请完成新消息的 GitHub 授权",
    });

    handleChatEvent(
      {
        auth_failed: true,
        provider,
        system_message: "旧消息的 GitHub 授权已失效",
      },
      olderContext,
    );

    expect(
      useAuthCardStore.getState().cardsByMessageId[
        olderContext.assistantMessageId
      ]?.[0],
    ).toMatchObject({
      authComplete: false,
      authFailed: true,
      message: "旧消息的 GitHub 授权已失效",
    });
    expect(
      useAuthCardStore.getState().cardsByMessageId[
        newerContext.assistantMessageId
      ]?.[0],
    ).toMatchObject({
      authComplete: false,
      authFailed: false,
      message: "请完成新消息的 GitHub 授权",
    });
  });

  it("ignores auth_failed when the message has no matching card", () => {
    handleChatEvent(
      {
        auth_failed: true,
        provider: "github-provider",
        system_message: "GitHub 授权失败",
      },
      { assistantMessageId: "missing-auth-message", fullText: "" },
    );

    expect(useAuthCardStore.getState().cardsByMessageId).toEqual({});
  });
});
