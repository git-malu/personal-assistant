import { describe, expect, it, vi } from "vitest";
import { onRequestPost } from "./ensure.js";

const request = new Request("https://example.com/api/runtime-session/ensure", {
  method: "POST",
  headers: {
    "x-hw-agentgateway-user-id": "user-1",
  },
});

describe("Runtime pre-warm BFF", () => {
  it("reuses an active user-scoped lease", async () => {
    const store = {
      getActiveLease: vi.fn().mockResolvedValue({
        status: "active",
        runtime_session_id: "runtime-1",
      }),
    };
    const response = await onRequestPost({
      request,
      env: {
        ALLOW_DEV_AUTH: "true",
        CONVERSATION_STORE: store,
        AGENTARTS_INVOCATIONS_URL:
          "https://runtime.example/runtimes/assistant/invocations",
      },
    });
    expect(await response.json()).toEqual({
      status: "ready",
      session_id: "runtime-1",
    });
  });

  it("degrades without blocking when sessions-start fails", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockRejectedValue(new Error("unavailable"));
    const store = {
      getActiveLease: vi.fn().mockResolvedValue(null),
      createStartingLease: vi.fn().mockResolvedValue({ id: "lease-1" }),
      degradeLease: vi.fn(),
    };
    try {
      const response = await onRequestPost({
        request,
        env: {
          ALLOW_DEV_AUTH: "true",
          CONVERSATION_STORE: store,
          AGENTARTS_INVOCATIONS_URL:
            "https://runtime.example/runtimes/assistant/invocations",
        },
      });
      expect(await response.json()).toEqual({ status: "degraded" });
      expect(store.degradeLease).toHaveBeenCalled();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
