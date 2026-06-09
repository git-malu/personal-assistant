import type {
  ChatModelAdapter,
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import type { SSEEvent } from "../types/chat";

const baseUrl: string = (
  import.meta.env.VITE_API_BASE_URL ?? ""
).replace(/\/$/, "");

/**
 * ChatModelAdapter that connects to the backend SSE API.
 *
 * - In dev mode (VITE_API_BASE_URL not set), requests go through the
 *   Vite dev proxy at `/api` → `localhost:8080`.
 * - In production, VITE_API_BASE_URL is set to the full AgentArts
 *   Runtime URL (e.g. `https://xxx.agentarts.cn-southwest-2.myhuaweicloud.com`).
 */
export const chatAdapter: ChatModelAdapter = {
  async *run({
    messages,
    abortSignal,
  }: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult, void> {
    // Extract the last user message text as the query
    const lastUserMessage = [...messages]
      .reverse()
      .find((m) => m.role === "user");
    const query: string =
      lastUserMessage?.content.find((p) => p.type === "text")?.text ?? "";

    const response = await fetch(
      `${baseUrl}/invocations/stream?q=${encodeURIComponent(query)}`,
      {
        headers: { Accept: "text/event-stream" },
        signal: abortSignal,
      },
    );

    if (!response.ok) {
      throw new Error(`Chat API error: ${response.status} ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No response body");
    }

    const decoder = new TextDecoder();
    let buffer = "";
    let fullText = "";
    let isDone = false;

    try {
      while (!isDone) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        // Normalize CRLF / CR → LF per SSE spec
        buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
        const lines = buffer.split("\n");
        // Keep the last partial line in the buffer
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;

          try {
            const parsed: SSEEvent = JSON.parse(raw);

            if (parsed.error) {
              throw new Error(parsed.error);
            }

            if (parsed.done) {
              isDone = true;
              break;
            }

            if (typeof parsed.token === "string") {
              fullText += parsed.token;
              yield {
                content: [{ type: "text", text: fullText }],
              };
            }
          } catch (e) {
            // If JSON parsing threw, bubble it up (real errors).
            // If it was our own `throw` from parsed.error, bubble it too.
            if (e instanceof SyntaxError) continue;
            throw e;
          }
        }
      }
    } finally {
      reader.releaseLock();
    }

    yield {
      content: [{ type: "text", text: fullText }],
      status: { type: "complete", reason: "stop" },
    };
  },
};
