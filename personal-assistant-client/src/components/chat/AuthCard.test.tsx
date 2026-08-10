import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useAuthCardStore } from "@/stores/auth-card-store";
import { AuthCard } from "./AuthCard";

describe("AuthCard", () => {
  afterEach(() => {
    useAuthCardStore.getState().clearAuth();
  });

  it("keeps rendering a historical message card after a newer Auth Card arrives", () => {
    const authStore = useAuthCardStore.getState();
    authStore.setAuth(
      "auth-message-1",
      "m365-provider-common",
      "https://auth-1.example.com",
      "请先完成日历授权",
    );
    authStore.setAuth(
      "auth-message-2",
      "m365-provider-common",
      "https://auth-2.example.com",
      "请再完成邮件授权",
    );

    render(<AuthCard messageId="auth-message-1" />);

    expect(screen.getByText("请先完成日历授权")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "点击授权" })).toHaveAttribute(
      "href",
      "https://auth-1.example.com",
    );
  });

  it("renders and dismisses same-message provider cards independently", () => {
    const authStore = useAuthCardStore.getState();
    authStore.setAuth(
      "report-message",
      "github-provider",
      "https://auth.example.com/github",
      "请完成 GitHub 授权",
    );
    authStore.setAuth(
      "report-message",
      "m365-email-provider",
      "https://auth.example.com/email",
      "请完成邮件授权",
    );
    authStore.setAuth(
      "report-message",
      "m365-calendar-provider",
      "https://auth.example.com/calendar",
      "请完成日历授权",
      "calendar-state",
    );
    authStore.setAuthComplete(
      "report-message",
      "github-provider",
      "GitHub 授权已完成",
    );
    authStore.setAuthFailed(
      "report-message",
      "m365-email-provider",
      "邮件授权失败",
    );

    const { container } = render(<AuthCard messageId="report-message" />);
    const cards = container.querySelectorAll('[data-slot="auth-card"]');

    expect(cards).toHaveLength(3);
    expect(within(cards[0] as HTMLElement).getByText("GitHub 授权已完成"))
      .toBeInTheDocument();
    expect(within(cards[1] as HTMLElement).getByText("邮件授权失败"))
      .toBeInTheDocument();
    expect(within(cards[2] as HTMLElement).getByText("请完成日历授权"))
      .toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "关闭 m365-email-provider 授权卡片",
      }),
    );

    expect(container.querySelectorAll('[data-slot="auth-card"]')).toHaveLength(
      2,
    );
    expect(screen.getByText("GitHub 授权已完成")).toBeInTheDocument();
    expect(screen.queryByText("邮件授权失败")).not.toBeInTheDocument();
    expect(screen.getByText("请完成日历授权")).toBeInTheDocument();
  });

  it("updates the latest card when a same-origin opener message arrives", async () => {
    const authStore = useAuthCardStore.getState();
    authStore.setAuth(
      "auth-message-1",
      "m365-calendar-provider",
      "https://auth.example.com",
      "请先完成日历授权",
      "signed-state",
    );

    render(<AuthCard />);

    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: {
            type: "m365-calendar-auth",
            request_id: "signed-state",
            status: "complete",
            provider: "m365-calendar-provider",
            message: "日历授权已完成，可以关闭此窗口并重试刚才的问题。",
            state: "signed-state",
          },
        }),
      );
    });

    await waitFor(() => {
      expect(
        screen.getByText("日历授权已完成，可以关闭此窗口并重试刚才的问题。"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("授权完成")).toBeInTheDocument();
  });

  it("ignores callback status for another OAuth state", async () => {
    const authStore = useAuthCardStore.getState();
    authStore.setAuth(
      "auth-message-1",
      "m365-calendar-provider",
      "https://auth.example.com",
      "请先完成日历授权",
      "current-state",
    );

    render(<AuthCard />);

    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: {
            type: "m365-calendar-auth",
            request_id: "other-state",
            status: "complete",
            provider: "m365-calendar-provider",
            message: "另一个授权已完成",
            state: "other-state",
          },
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByText("请先完成日历授权")).toBeInTheDocument();
    });
    expect(screen.queryByText("另一个授权已完成")).not.toBeInTheDocument();
  });

  it("ignores calendar callback status without OAuth state", async () => {
    const authStore = useAuthCardStore.getState();
    authStore.setAuth(
      "auth-message-1",
      "m365-calendar-provider",
      "https://auth.example.com",
      "请先完成日历授权",
      "current-state",
    );

    render(<AuthCard />);

    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          origin: window.location.origin,
          data: {
            type: "m365-calendar-auth",
            request_id: "",
            status: "failed",
            provider: "m365-calendar-provider",
            message: "缺少 state 的失败状态",
          },
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByText("请先完成日历授权")).toBeInTheDocument();
    });
    expect(screen.queryByText("缺少 state 的失败状态")).not.toBeInTheDocument();
  });
});
