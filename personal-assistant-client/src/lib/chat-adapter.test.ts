import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { chatAdapter } from "./chat-adapter";
import { useAuthStore } from "@/stores/auth-store";
import type { ChatModelRunOptions, ChatModelRunResult } from "@assistant-ui/react";
import type { ThreadMessage, ThreadUserMessagePart } from "@assistant-ui/core";

// Mock the auth module to control acquireIdTokenSilently behavior
const mockAcquireIdTokenSilently = vi.fn();
vi.mock("@/lib/auth", () => ({
  acquireIdTokenSilently: () => mockAcquireIdTokenSilently(),
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
    mockAcquireIdTokenSilently.mockReset();
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
      expect(init.body).toBe(
        JSON.stringify({ message: "Hello World!", stream: true }),
      );
    });

    it("builds URL with empty baseUrl when VITE_API_BASE_URL is unset", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("test");

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toBe("/invocations");
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
      useAuthStore.getState().setIdToken("test-token-123");

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("auth test");

      const init = mockFetch.mock.calls[0][1] as RequestInit;
      const headers = init.headers as Record<string, string>;
      expect(headers).toHaveProperty("Authorization");
      expect(headers["Authorization"]).toBe("Bearer test-token-123");
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

  describe("401 / 403 auth refresh", () => {
    it("on 401: calls acquireIdTokenSilently, clears token when refresh returns null, throws auth error", async () => {
      // Set initial token
      useAuthStore.getState().setIdToken("expired-token");
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

      // Verify acquireIdTokenSilently was called
      expect(mockAcquireIdTokenSilently).toHaveBeenCalledTimes(1);

      // Verify store token was cleared
      expect(useAuthStore.getState().idToken).toBeNull();
    });

    it("on 403: calls acquireIdTokenSilently, clears token when refresh returns null, throws auth error", async () => {
      useAuthStore.getState().setIdToken("forbidden-token");
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
    });

    it("on 401: calls acquireIdTokenSilently, updates store with fresh token, still throws auth error", async () => {
      useAuthStore.getState().setIdToken("expired-token");
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

      // Verify acquireIdTokenSilently was called
      expect(mockAcquireIdTokenSilently).toHaveBeenCalledTimes(1);

      // Verify store was cleared after fresh token also failed
      expect(useAuthStore.getState().idToken).toBeNull();
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
      expect(init.body).toBe(JSON.stringify({ message: "", stream: true }));
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
});
