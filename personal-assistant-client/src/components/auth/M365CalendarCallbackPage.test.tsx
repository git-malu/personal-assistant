import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildBackendCalendarCallbackUrl,
  getCalendarCallbackState,
} from "./M365CalendarCallbackPage";
import M365CalendarCallbackPage from "./M365CalendarCallbackPage";

describe("M365CalendarCallbackPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("builds the local fallback backend callback URL", () => {
    expect(
      buildBackendCalendarCallbackUrl(
        "http://localhost:5173",
        "?session_uri=urn:session:test&state=signed-state",
      ).toString(),
    ).toBe(
      "http://localhost:5173/invocations/auth/oauth2/callback/m365-calendar?session_uri=urn:session:test&state=signed-state",
    );
  });

  it("extracts signed callback state from state or custom_state", () => {
    expect(getCalendarCallbackState("?state=signed-state")).toBe(
      "signed-state",
    );
    expect(getCalendarCallbackState("?custom_state=custom-signed-state")).toBe(
      "custom-signed-state",
    );
  });

  it("uses the local fallback proxy without Authorization and shows result", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          type: "m365-calendar-auth",
          requestId: "signed-state",
          provider: "m365-calendar-provider",
          status: "complete",
          message: "日历授权已完成，可以关闭此窗口并重试刚才的问题。",
          state: "signed-state",
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    window.history.pushState(
      {},
      "",
      "/auth/callback/m365-calendar?session_uri=urn:session:test&state=signed-state",
    );

    render(<M365CalendarCallbackPage />);

    await waitFor(() => {
      expect(screen.getByText("授权完成")).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url.toString()).toBe(
      "http://localhost:3000/invocations/auth/oauth2/callback/m365-calendar?session_uri=urn:session:test&state=signed-state",
    );
    expect(init.headers).toEqual({ Accept: "application/json" });
  });

  it("broadcasts a failed state when the local fallback cannot complete", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("network error"));
    const postMessageMock = vi.fn();
    const closeMock = vi.fn();
    class MockBroadcastChannel {
      name: string;

      constructor(name: string) {
        this.name = name;
      }

      postMessage = postMessageMock;
      close = closeMock;
    }

    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("BroadcastChannel", MockBroadcastChannel);
    window.history.pushState(
      {},
      "",
      "/auth/callback/m365-calendar?session_uri=urn:session:test&state=signed-state&error_description=本地授权失败",
    );

    render(<M365CalendarCallbackPage />);

    await waitFor(() => {
      expect(screen.getByText("授权失败")).toBeInTheDocument();
    });
    expect(screen.getByText("本地授权失败")).toBeInTheDocument();
    expect(postMessageMock).toHaveBeenCalledWith(
      expect.objectContaining({
        requestId: "signed-state",
        state: "signed-state",
        status: "failed",
      }),
    );
  });
});
