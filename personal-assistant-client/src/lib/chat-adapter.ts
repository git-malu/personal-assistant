import type {
  ChatModelAdapter,
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import type { SSEEvent } from "../types/chat";
import { useAuthStore } from "@/stores/auth-store";
import { acquireIdTokenSilently } from "@/lib/auth";

const baseUrl: string = (
  import.meta.env.VITE_API_BASE_URL ?? ""
).replace(/\/$/, "");

/**
 * Decode a base64url-encoded string to a native JavaScript string.
 *
 * Unlike atob(), this handles:
 * - base64url alphabet (- → +, _ → /)
 * - missing padding
 * - UTF-8 byte sequences in the decoded payload (e.g. Chinese names in claims)
 */
function base64UrlDecode(str: string): string {
  // Restore base64url → standard base64
  let base64 = str.replace(/-/g, "+").replace(/_/g, "/");
  // Restore padding
  while (base64.length % 4 !== 0) {
    base64 += "=";
  }
  // Decode binary string to UTF-8
  const binary = atob(base64);
  return new TextDecoder().decode(
    Uint8Array.from(binary, (c) => c.charCodeAt(0)),
  );
}

function extractUserIdFromToken(idToken: string): string | undefined {
  try {
    const payload = JSON.parse(base64UrlDecode(idToken.split(".")[1]));
    return (payload as Record<string, unknown>).sub as string | undefined
        ?? (payload as Record<string, unknown>).oid as string | undefined;
  } catch {
    return undefined;
  }
}

/** Check if token expires within the next 60 seconds */
function isTokenExpiringSoon(idToken: string): boolean {
  try {
    const payload = JSON.parse(base64UrlDecode(idToken.split(".")[1]));
    const exp = (payload as Record<string, unknown>).exp as number;
    return Date.now() >= (exp - 60) * 1000;
  } catch {
    return true; // can't parse — assume expired
  }
}

function getSessionId(): string {
  try {
    const existing = localStorage.getItem("agentarts-session-id");
    if (existing) return existing;
    const id = crypto.randomUUID();
    localStorage.setItem("agentarts-session-id", id);
    return id;
  } catch {
    return crypto.randomUUID();
  }
}

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

    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let fullText = "";

    try {
      // Get current idToken and refresh if close to expiry
      let idToken = useAuthStore.getState().idToken;
      if (idToken && isTokenExpiringSoon(idToken)) {
        const fresh = await acquireIdTokenSilently();
        if (fresh) {
          useAuthStore.getState().setIdToken(fresh);
          idToken = fresh;
        }
      }

      const headers: Record<string, string> = {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        "x-hw-agentarts-session-id": getSessionId(),
      };
      if (idToken) {
        headers["Authorization"] = `Bearer ${idToken}`;
        const userId = extractUserIdFromToken(idToken);
        if (userId) {
          headers["X-HW-AgentGateway-User-Id"] = userId;
        }
      }

      let response = await fetch(`${baseUrl}/invocations`, {
        method: "POST",
        headers,
        body: JSON.stringify({ message: query, stream: true }),
        signal: abortSignal,
      });

      // Token may have expired — try silent refresh once
      if ((response.status === 401 || response.status === 403) && idToken) {
        const freshToken = await acquireIdTokenSilently();
        if (freshToken) {
          useAuthStore.getState().setIdToken(freshToken);
          headers["Authorization"] = `Bearer ${freshToken}`;
          const userId = extractUserIdFromToken(freshToken);
          if (userId) {
            headers["X-HW-AgentGateway-User-Id"] = userId;
          }
          response = await fetch(`${baseUrl}/invocations`, {
            method: "POST",
            headers,
            body: JSON.stringify({ message: query, stream: true }),
            signal: abortSignal,
          });
        } else {
          useAuthStore.getState().clearToken();
          throw new Error("Authentication required. Please sign in.");
        }
      }

      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          useAuthStore.getState().clearToken();
          throw new Error("Authentication required. Please sign in.");
        }
        throw new Error(`Chat API error: ${response.status} ${response.statusText}`);
      }

      reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body");
      }

      const decoder = new TextDecoder();
      let buffer = "";
      let isDone = false;

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
      reader?.releaseLock();
    }

    yield {
      content: [{ type: "text", text: fullText }],
      status: { type: "complete", reason: "stop" },
    };
  },
};
