import { describe, it, expect, vi, afterEach } from "vitest";
import { chatAdapter } from "./chat-adapter";
import type { ChatModelRunOptions, ChatModelRunResult } from "@assistant-ui/react";
import type { ThreadMessage, ThreadUserMessagePart } from "@assistant-ui/core";

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

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  describe("URL construction", () => {
    it("uses /invocations/stream path with encoded query", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("Hello World!");

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain("/invocations/stream?q=");
      expect(url).toContain("Hello%20World!");
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
      expect(url).toMatch(/^\/invocations\/stream\?q=/);
    });

    it("sends Accept: text/event-stream header", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        body: createMockStream([]),
      });
      globalThis.fetch = mockFetch as unknown as typeof fetch;

      await collectResults("header test");

      const init = mockFetch.mock.calls[0][1] as RequestInit;
      expect(init.headers).toEqual({ Accept: "text/event-stream" });
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
      expect(url).toContain("/invocations/stream?q=");
    });
  });
});
