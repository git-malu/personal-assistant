import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { chatAdapter, getSessionId, resetSessionId } from "./chat-adapter";
import { useAuthCardStore } from "@/stores/auth-card-store";
import { useAuthStore } from "@/stores/auth-store";
import type { ChatModelRunOptions, ChatModelRunResult } from "@assistant-ui/react";
import type { ThreadMessage, ThreadUserMessagePart } from "@assistant-ui/core";

// Mock the auth module to control acquireIdTokenSilently behavior
const { mockAcquireIdTokenSilently, mockClearInboundAuthSession } = vi.hoisted(
  () => ({
    mockAcquireIdTokenSilently: vi.fn(),
    mockClearInboundAuthSession: vi.fn(),
  }),
);
vi.mock("@/lib/auth", () => ({
  acquireIdTokenSilently: () => mockAcquireIdTokenSilently(),
  clearInboundAuthSession: () => mockClearInboundAuthSession(),
}));

/**
 * Helper to create a minimal ThreadUserMessage for testing.
 * The adapter only reads role and the first text-type content part.
 */
function makeUserMessage(query: string): ThreadMessage {
  const textPart: ThreadUserMessagePart = { type: "text", text: query };
  return {
    id: `msg-${Math.random().toString(36).slice(2)}`,
    createdAt: new Date(),
    role: "user" as const,
    content: [textPart],
    attachments: [],
    metadata: { custom: {} },
  };
}

/**
 * Helper to create a minimal ChatModelRunOptions for testing.
 * The adapter only reads messages, abortSignal — the rest are filled with
 * no-op defaults since ChatModelRunOptions requires them.
 */
function createOptions(
  query: string,
  abortSignal?: AbortSignal,
): ChatModelRunOptions {
  return {
    messages: [makeUserMessage(query)],
    abortSignal: abortSignal ?? new AbortController().signal,
    runConfig: {},
    context: {},
    unstable_getMessage: () =>
      makeUserMessage(query),
  };
}

/**
 * Helper to create a mock ReadableStream from an array of Uint8Array chunks.
 */
function createMockStream(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

const encoder = new TextEncoder();

/**
 * Convenience helper: calls chatAdapter.run and collects all yielded results.
 * chatAdapter.run returns Promise | AsyncGenerator; our adapter is always
 * an async generator, so `for await...of` works at runtime. This wrapper
 * narrows the type for TypeScript.
 */
async function collectResults(
  query: string,
  signal?: AbortSignal,
): Promise<ChatModelRunResult[]> {
  const results: ChatModelRunResult[] = [];
  const gen = chatAdapter.run(createOptions(query, signal));
  // The type is Promise<ChatModelRunResult> | AsyncGenerator<...>;
  // we know at runtime it's an async generator.
  for await (const result of gen as AsyncGenerator<ChatModelRunResult, void>) {
    results.push(result);
  }
  return results;
}

describe("chatAdapter", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    // Reset auth store to clean state before each test
    useAuthStore.getState().clearToken();
    useAuthCardStore.getState().clearAuth();
    mockAcquireIdTokenSilently.mockReset();
    mockClearInboundAuthSession.mockReset();
    mockClearInboundAuthSession.mockImplementation(async () => {
      useAuthStore.getState().clearToken();
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  describe("URL construction", () => {
    it("uses POST /invocations with stream body", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("Hello World!");

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const url = mockFetch.mock.calls[0][0] as string;
      const init = mockFetch.mock.calls[0][1] as RequestInit;
      expect(url).toBe("/invocations");
      expect(init.method).toBe("POST");
      expect(JSON.parse(String(init.body))).toMatchObject({
        message: "Hello World!",
        stream: true,
      });
    });

    it("sends streaming headers and excludes Authorization when idToken is null", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("header test");

      const init = mockFetch.mock.calls[0][1] as RequestInit;
      expect(init.headers).toEqual(
        expect.objectContaining({
          Accept: "text/event-stream",
          "Content-Type": "application/json",
        }),
      );
      // Authorization should NOT be present when idToken is null
      expect(init.headers).not.toHaveProperty("Authorization");
    });

    it("passes the abort signal to fetch", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      const controller = new AbortController();
      await collectResults("abort test", controller.signal);

      const init = mockFetch.mock.calls[0][1] as RequestInit;
      expect(init.signal).toBe(controller.signal);
    });
  });

  describe("SSE token parsing", () => {
    it("preserves a pending Auth Card when the user sends another message", async () => {
      useAuthCardStore.getState().setAuth(
        "auth-message",
        "m365-provider-common",
        "https://auth.example.com",
        "请完成授权",
      );
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([
          encoder.encode("data: " + JSON.stringify({ done: true }) + "\n"),
        ]),
      }) as unknown as typeof fetch;

      await collectResults("稍后再授权");

      expect(useAuthCardStore.getState()).toMatchObject({
        messageId: "auth-message",
        provider: "m365-provider-common",
        authUrl: "https://auth.example.com",
        message: "请完成授权",
        authComplete: false,
      });
    });

    it("preserves a completed Auth Card when the user sends another message", async () => {
      const authStore = useAuthCardStore.getState();
      authStore.setAuth(
        "auth-message",
        "m365-provider-common",
        "https://auth.example.com",
        "请完成授权",
      );
      authStore.setAuthComplete("m365-provider-common", "授权已完成 ✅");
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([
          encoder.encode("data: " + JSON.stringify({ done: true }) + "\n"),
        ]),
      }) as unknown as typeof fetch;

      await collectResults("继续处理邮件");

      expect(useAuthCardStore.getState()).toMatchObject({
        messageId: "auth-message",
        provider: "m365-provider-common",
        authUrl: "https://auth.example.com",
        message: "授权已完成 ✅",
        authComplete: true,
      });
    });

    it("keeps historical Auth Cards when a new Auth Card arrives", () => {
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

      expect(useAuthCardStore.getState().cardsByMessageId).toMatchObject({
        "auth-message-1": {
          authUrl: "https://auth-1.example.com",
          message: "请先完成日历授权",
          authComplete: false,
        },
        "auth-message-2": {
          authUrl: "https://auth-2.example.com",
          message: "请再完成邮件授权",
          authComplete: false,
        },
      });
      expect(useAuthCardStore.getState()).toMatchObject({
        messageId: "auth-message-2",
        authUrl: "https://auth-2.example.com",
      });
    });

    it("yields content chunks for SSE token events", async () => {
      const chunks = [
        encoder.encode("data: " + JSON.stringify({ token: "Hello" }) + "\n"),
        encoder.encode("data: " + JSON.stringify({ token: " World" }) + "\n"),
      ];
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      const results = await collectResults("hi");
      const texts = results
        .map((r) => r.content?.[0])
        .filter((c): c is { type: "text"; text: string } => c?.type === "text")
        .map((c) => c.text);

      expect(texts).toContain("Hello");
      expect(texts).toContain("Hello World");
    });

    it("accumulates text across multiple tokens", async () => {
      const tokens = ["The", " quick", " brown", " fox"];
      const chunks = tokens.map((token) =>
        encoder.encode("data: " + JSON.stringify({ token }) + "\n"),
      );
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      const results = await collectResults("fox");
      const texts = results
        .map((r) => r.content?.[0])
        .filter((c): c is { type: "text"; text: string } => c?.type === "text")
        .map((c) => c.text);

      expect(texts[texts.length - 1]).toBe("The quick brown fox");
    });

    it("emits complete status at end of stream", async () => {
      const chunks = [
        encoder.encode("data: " + JSON.stringify({ token: "Hi" }) + "\n"),
        encoder.encode("data: " + JSON.stringify({ done: true }) + "\n"),
      ];
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      const results = await collectResults("hi");

      const finalResult = results[results.length - 1];
      expect(finalResult?.status).toEqual({
        type: "complete",
        reason: "stop",
      });
    });

    it("renders auth_required in the Auth Card without appending it to message text", async () => {
      const chunks = [
        encoder.encode(
          "data: " +
            JSON.stringify({
              system_message: "请完成授权",
              auth_required: true,
              auth_url: "https://auth.example.com",
              provider: "m365-provider-common",
            }) +
            "\n",
        ),
        encoder.encode("data: " + JSON.stringify({ done: true }) + "\n"),
      ];
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      }) as unknown as typeof fetch;

      const results = await collectResults("查看收件箱");
      const finalText = results[results.length - 1]?.content?.[0];
      const authState = useAuthCardStore.getState();

      expect(finalText).toEqual({ type: "text", text: "" });
      expect(authState).toMatchObject({
        provider: "m365-provider-common",
        authUrl: "https://auth.example.com",
        message: "请完成授权",
        authComplete: false,
      });
    });

    it("marks a matching pending Auth Card complete without appending completion text", async () => {
      const chunks = [
        encoder.encode(
          "data: " +
            JSON.stringify({
              system_message: "请完成授权",
              auth_required: true,
              auth_url: "https://auth.example.com",
              provider: "m365-provider-common",
            }) +
            "\n",
        ),
        encoder.encode(
          "data: " +
            JSON.stringify({
              system_message: "授权已完成 ✅",
              auth_complete: true,
              provider: "m365-provider-common",
            }) +
            "\n",
        ),
        encoder.encode("data: " + JSON.stringify({ done: true }) + "\n"),
      ];
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      }) as unknown as typeof fetch;

      const results = await collectResults("查看收件箱");
      const finalText = results[results.length - 1]?.content?.[0];

      expect(finalText).toEqual({ type: "text", text: "" });
      expect(useAuthCardStore.getState()).toMatchObject({
        message: "授权已完成 ✅",
        authComplete: true,
      });
    });

    it("ignores auth_complete when no matching pending Auth Card exists", async () => {
      const chunks = [
        encoder.encode(
          "data: " +
            JSON.stringify({
              system_message: "授权已完成 ✅",
              auth_complete: true,
              provider: "m365-provider-common",
            }) +
            "\n",
        ),
        encoder.encode("data: " + JSON.stringify({ done: true }) + "\n"),
      ];
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      }) as unknown as typeof fetch;

      const results = await collectResults("查看收件箱");
      const finalText = results[results.length - 1]?.content?.[0];

      expect(finalText).toEqual({ type: "text", text: "" });
      expect(useAuthCardStore.getState()).toMatchObject({
        provider: null,
        authUrl: null,
        message: "",
        authComplete: false,
      });
    });

    it("continues appending non-auth system messages to message text", async () => {
      const chunks = [
        encoder.encode(
          "data: " +
            JSON.stringify({ system_message: "普通系统消息" }) +
            "\n",
        ),
        encoder.encode("data: " + JSON.stringify({ done: true }) + "\n"),
      ];
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      }) as unknown as typeof fetch;

      const results = await collectResults("test");
      const texts = results
        .flatMap((result) => result.content ?? [])
        .filter(
          (content): content is { type: "text"; text: string } =>
            content.type === "text",
        )
        .map((content) => content.text);

      expect(texts).toContain("普通系统消息");
    });
  });

  describe("error handling", () => {
    it("throws on non-ok HTTP response", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await expect(collectResults("error test")).rejects.toThrow(
        "Chat API error: 500 Internal Server Error",
      );
    });

    it("throws on missing response body", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: null,
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await expect(collectResults("no body")).rejects.toThrow(
        "No response body",
      );
    });

    it("throws on SSE error event", async () => {
      const chunks = [
        encoder.encode(
          "data: " + JSON.stringify({ error: "Backend failure" }) + "\n",
        ),
      ];
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await expect(collectResults("error SSE")).rejects.toThrow(
        "Backend failure",
      );
    });

    it("skips non-data lines gracefully", async () => {
      const chunks = [
        encoder.encode(":comment\n"),
        encoder.encode("event: message\n"),
        encoder.encode("data: " + JSON.stringify({ token: "Valid" }) + "\n"),
      ];
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      const results = await collectResults("comments");
      const texts = results
        .map((r) => r.content?.[0])
        .filter((c): c is { type: "text"; text: string } => c?.type === "text")
        .map((c) => c.text);

      expect(texts.some((t) => t === "Valid")).toBe(true);
    });

    it("skips unparseable JSON data lines without crashing", async () => {
      const chunks = [
        encoder.encode("data: not-json\n"),
        encoder.encode(
          "data: " + JSON.stringify({ token: "After bad" }) + "\n",
        ),
      ];
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream(chunks),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      const results = await collectResults("bad json");
      const texts = results
        .map((r) => r.content?.[0])
        .filter((c): c is { type: "text"; text: string } => c?.type === "text")
        .map((c) => c.text);

      expect(texts.some((t) => t === "After bad")).toBe(true);
    });
  });

  describe("auth header", () => {
    it("includes Authorization: Bearer header when idToken is set", async () => {
      // Set idToken in the zustand store
      const idToken = makeTestJWT();
      useAuthStore.getState().setIdToken(idToken);

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("auth test");

      const init = mockFetch.mock.calls[0][1] as RequestInit;
      const headers = init.headers as Record<string, string>;
      expect(headers).toHaveProperty("Authorization");
      expect(headers["Authorization"]).toBe(`Bearer ${idToken}`);
    });

    it("does NOT include Authorization header when idToken is null", async () => {
      // Ensure idToken is null (already reset in beforeEach)
      expect(useAuthStore.getState().idToken).toBeNull();

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("no auth test");

      const init = mockFetch.mock.calls[0][1] as RequestInit;
      const headers = init.headers as Record<string, string>;
      expect(headers).not.toHaveProperty("Authorization");
    });
  });

  /**
   * Helper to create a minimal valid-looking JWT token.
   * Uses a future exp to prevent proactive token refresh from triggering.
   */
  function makeTestJWT(expOffsetSec = 3600): string {
    const payload = { exp: Math.floor(Date.now() / 1000) + expOffsetSec };
    const base64Payload = btoa(JSON.stringify(payload));
    return `header.${base64Payload}.signature`;
  }

  describe("401 / 403 auth refresh", () => {
    it("on 401: calls acquireIdTokenSilently, clears token when refresh returns null, throws auth error", async () => {
      // Use a valid JWT so proactive refresh (isTokenExpiringSoon) does not trigger
      useAuthStore.getState().setIdToken(makeTestJWT());
      mockAcquireIdTokenSilently.mockResolvedValue(null);

      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: "Unauthorized",
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await expect(collectResults("401 test")).rejects.toThrow(
        "Authentication required. Please sign in.",
      );

      // Verify acquireIdTokenSilently was called exactly once (401 handler)
      expect(mockAcquireIdTokenSilently).toHaveBeenCalledTimes(1);

      // Verify store token was cleared
      expect(useAuthStore.getState().idToken).toBeNull();
      expect(mockClearInboundAuthSession).toHaveBeenCalledTimes(1);
    });

    it("on 403: calls acquireIdTokenSilently, clears token when refresh returns null, throws auth error", async () => {
      useAuthStore.getState().setIdToken(makeTestJWT());
      mockAcquireIdTokenSilently.mockResolvedValue(null);

      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        statusText: "Forbidden",
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await expect(collectResults("403 test")).rejects.toThrow(
        "Authentication required. Please sign in.",
      );

      expect(mockAcquireIdTokenSilently).toHaveBeenCalledTimes(1);
      expect(useAuthStore.getState().idToken).toBeNull();
      expect(mockClearInboundAuthSession).toHaveBeenCalledTimes(1);
    });

    it("on 401: calls acquireIdTokenSilently, updates store with fresh token, still throws auth error", async () => {
      useAuthStore.getState().setIdToken(makeTestJWT());
      mockAcquireIdTokenSilently.mockResolvedValue("fresh-token-456");

      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        statusText: "Unauthorized",
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await expect(collectResults("401 refresh test")).rejects.toThrow(
        "Authentication required. Please sign in.",
      );

      // Verify acquireIdTokenSilently was called exactly once (401 handler)
      expect(mockAcquireIdTokenSilently).toHaveBeenCalledTimes(1);

      expect(mockFetch).toHaveBeenCalledTimes(2);
      const retryInit = mockFetch.mock.calls[1][1] as RequestInit;
      const retryHeaders = retryInit.headers as Record<string, string>;
      expect(retryHeaders["Authorization"]).toBe("Bearer fresh-token-456");

      // Verify store was cleared after fresh token also failed
      expect(useAuthStore.getState().idToken).toBeNull();
      expect(mockClearInboundAuthSession).toHaveBeenCalledTimes(1);
    });
  });

  describe("proactive token refresh (CT-AUTH-02)", () => {
    it("refreshes token before fetch when token is expiring soon", async () => {
      // Token that expires in 30 seconds (within the 60s threshold)
      useAuthStore.getState().setIdToken(makeTestJWT(30));
      mockAcquireIdTokenSilently.mockResolvedValue("fresh-proactive-token");

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("proactive refresh test");

      // acquireIdTokenSilently should have been called proactively (before fetch)
      expect(mockAcquireIdTokenSilently).toHaveBeenCalledTimes(1);

      // The fresh token should be in the store
      expect(useAuthStore.getState().idToken).toBe("fresh-proactive-token");

      // The Authorization header should contain the fresh token
      const init = mockFetch.mock.calls[0][1] as RequestInit;
      const headers = init.headers as Record<string, string>;
      expect(headers).toHaveProperty("Authorization");
      expect(headers["Authorization"]).toBe("Bearer fresh-proactive-token");
    });

    it("does not refresh token when token is not expiring soon", async () => {
      // Token that expires in 1 hour (well outside the 60s threshold)
      useAuthStore.getState().setIdToken(makeTestJWT(3600));
      mockAcquireIdTokenSilently.mockResolvedValue("should-not-be-called");

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("no-refresh-needed test");

      // acquireIdTokenSilently should NOT have been called
      expect(mockAcquireIdTokenSilently).not.toHaveBeenCalled();

      // Original token should still be in the store
      expect(useAuthStore.getState().idToken).toBeTruthy();
      expect(useAuthStore.getState().idToken).not.toBe("should-not-be-called");
    });

    it("signs out and does not send an expired token when proactive refresh returns null", async () => {
      // Token expiring soon, but refresh fails — the adapter must not send the
      // original expired token and wait for the backend to reject it.
      const nearExpiryToken = makeTestJWT(30);
      useAuthStore.getState().setIdToken(nearExpiryToken);
      mockAcquireIdTokenSilently.mockResolvedValue(null);

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await expect(collectResults("refresh-fails test")).rejects.toThrow(
        "Authentication required. Please sign in.",
      );

      // acquireIdTokenSilently should have been called
      expect(mockAcquireIdTokenSilently).toHaveBeenCalledTimes(1);

      expect(mockFetch).not.toHaveBeenCalled();
      expect(useAuthStore.getState().idToken).toBeNull();
      expect(mockClearInboundAuthSession).toHaveBeenCalledTimes(1);
    });
  });

  describe("empty query", () => {
    it("handles empty query string gracefully", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      // No user messages — should result in query = ""
      const emptyOptions: ChatModelRunOptions = {
        messages: [],
        abortSignal: new AbortController().signal,
        runConfig: {},
        context: {},
        unstable_getMessage: () => makeUserMessage(""),
      };

      const gen = chatAdapter.run(emptyOptions);
      for await (const _result of gen as AsyncGenerator<ChatModelRunResult, void>) {
        /* consume */
      }

      const url = mockFetch.mock.calls[0][0] as string;
      const init = mockFetch.mock.calls[0][1] as RequestInit;
      expect(url).toBe("/invocations");
      expect(JSON.parse(String(init.body))).toMatchObject({
        message: "",
        stream: true,
      });
    });
  });

  describe("session ID header", () => {
    beforeEach(() => {
      localStorage.clear();
    });

    afterEach(() => {
      localStorage.clear();
    });

    it("sends x-hw-agentarts-session-id header with each request", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("test session");

      const init = mockFetch.mock.calls[0][1] as RequestInit;
      const headers = init.headers as Record<string, string>;
      expect(headers).toHaveProperty("x-hw-agentarts-session-id");
      expect(headers["x-hw-agentarts-session-id"]).toBeTruthy();
    });

    it("uses same session ID across multiple requests", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("request 1");
      await collectResults("request 2");

      const headers1 = mockFetch.mock.calls[0][1].headers as Record<string, string>;
      const headers2 = mockFetch.mock.calls[1][1].headers as Record<string, string>;

      expect(headers1["x-hw-agentarts-session-id"]).toBe(
        headers2["x-hw-agentarts-session-id"],
      );
    });

    it("session ID is a valid UUID v4 format", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("uuid test");

      const headers = mockFetch.mock.calls[0][1].headers as Record<string, string>;
      const sessionId = headers["x-hw-agentarts-session-id"];

      // UUID v4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
      const uuidV4Regex =
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      expect(sessionId).toMatch(uuidV4Regex);
    });

    it("persists session ID in localStorage under agentarts-session-id key", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("persist test");

      const stored = localStorage.getItem("agentarts-session-id");
      expect(stored).toBeTruthy();

      const headers = mockFetch.mock.calls[0][1].headers as Record<string, string>;
      expect(stored).toBe(headers["x-hw-agentarts-session-id"]);
    });

    it("reuses existing session ID from localStorage", async () => {
      // Simulate a previously stored session ID
      const existingId = "12345678-1234-4123-8123-123456789abc";
      localStorage.setItem("agentarts-session-id", existingId);

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("reuse test");

      const headers = mockFetch.mock.calls[0][1].headers as Record<string, string>;
      expect(headers["x-hw-agentarts-session-id"]).toBe(existingId);
    });

    it("falls back to non-persisted UUID when localStorage throws", async () => {
      // Simulate localStorage being completely unavailable (e.g., SecurityError)
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
        throw new DOMException("Blocked", "SecurityError");
      });
      const setItemSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
        throw new DOMException("Blocked", "SecurityError");
      });

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("fallback test");

      // Should still receive a session ID header even when localStorage fails
      const headers = mockFetch.mock.calls[0][1].headers as Record<string, string>;
      expect(headers).toHaveProperty("x-hw-agentarts-session-id");
      const sessionId = headers["x-hw-agentarts-session-id"];
      expect(sessionId).toBeTruthy();

      // The fallback ID should be a valid UUID v4
      const uuidV4Regex =
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      expect(sessionId).toMatch(uuidV4Regex);

      // setItem should never have been called (no persistence in fallback)
      expect(setItemSpy).not.toHaveBeenCalled();

      vi.restoreAllMocks();
    });
  });

  describe("resetSessionId", () => {
    beforeEach(() => {
      localStorage.clear();
    });

    afterEach(() => {
      localStorage.clear();
      vi.restoreAllMocks();
    });

    it("UT-RS-01: removes agentarts-session-id from localStorage", () => {
      localStorage.setItem("agentarts-session-id", "test-session-id");
      expect(localStorage.getItem("agentarts-session-id")).toBe("test-session-id");

      resetSessionId();

      expect(localStorage.getItem("agentarts-session-id")).toBeNull();
    });

    it("UT-RS-02: is a no-op when key does not exist", () => {
      expect(localStorage.getItem("agentarts-session-id")).toBeNull();

      expect(() => resetSessionId()).not.toThrow();

      expect(localStorage.getItem("agentarts-session-id")).toBeNull();
    });

    it("UT-RS-03: silently handles localStorage errors (privacy mode)", () => {
      vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
        throw new DOMException("Blocked", "SecurityError");
      });

      expect(() => resetSessionId()).not.toThrow();
    });

    it("UT-RS-04: after resetSessionId, getSessionId returns a new UUID", () => {
      // Set an existing session ID
      localStorage.setItem("agentarts-session-id", "old-session-id");

      // Record the old value
      const oldId = getSessionId();
      expect(oldId).toBe("old-session-id");

      // Reset the session ID
      resetSessionId();

      // Get new session ID
      const newId = getSessionId();

      // New ID should differ from old
      expect(newId).not.toBe(oldId);

      // New ID should be a valid UUID v4
      const uuidV4Regex =
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      expect(newId).toMatch(uuidV4Regex);

      // New ID should also be persisted in localStorage
      expect(localStorage.getItem("agentarts-session-id")).toBe(newId);
    });
  });
});
