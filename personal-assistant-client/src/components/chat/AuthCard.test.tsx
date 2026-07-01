import { act, render, screen, waitFor } from "@testing-library/react";
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
