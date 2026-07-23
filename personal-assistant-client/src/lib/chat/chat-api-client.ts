import { acquireIdTokenSilently, clearInboundAuthSession } from "@/lib/auth";
import { useAuthStore } from "@/stores/auth-store";
import { isTokenExpiringSoon } from "./jwt";

const AUTH_REQUIRED_MESSAGE = "Authentication required. Please sign in.";
const CANCELLATION_TIMEOUT_MS = 15_000;

export class ChatApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly detail?: string,
  ) {
    super(message);
    this.name = "ChatApiError";
  }
}

export function buildHeaders(
  idToken: string | null,
  accept = "text/event-stream",
): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: accept,
    "Content-Type": "application/json",
  };
  if (idToken) {
    headers.Authorization = `Bearer ${idToken}`;
  }
  return headers;
}

function sendChatRequest(
  query: string,
  conversationId: string,
  clientMessageId: string,
  abortSignal: AbortSignal,
  headers: Record<string, string>,
): Promise<Response> {
  return fetch("/invocations", {
    method: "POST",
    headers,
    body: JSON.stringify({
      conversation_id: conversationId,
      client_message_id: clientMessageId,
      message: query,
      stream: true,
    }),
    signal: abortSignal,
    credentials: "same-origin",
  });
}

export async function getRequestToken(): Promise<string | null> {
  let idToken = useAuthStore.getState().idToken;
  if (idToken && isTokenExpiringSoon(idToken)) {
    const freshToken = await acquireIdTokenSilently();
    if (freshToken) {
      useAuthStore.getState().setIdToken(freshToken);
      idToken = freshToken;
    } else {
      await clearInboundAuthSession();
      throw new Error(AUTH_REQUIRED_MESSAGE);
    }
  }
  return idToken;
}

async function readResponseDetail(
  response: Response,
): Promise<{ code?: string; detail?: string }> {
  try {
    const body = (await response.json()) as {
      code?: unknown;
      detail?: unknown;
    };
    return {
      code: typeof body.code === "string" ? body.code : undefined,
      detail: typeof body.detail === "string" ? body.detail : undefined,
    };
  } catch {
    return {};
  }
}

async function throwResponseError(response: Response): Promise<never> {
  if (response.status === 401 || response.status === 403) {
    await clearInboundAuthSession();
    throw new Error(AUTH_REQUIRED_MESSAGE);
  }

  const { code, detail } = await readResponseDetail(response);
  if (response.status === 409 && code === "conversation_busy") {
    throw new ChatApiError(
      "This conversation is already processing a message. Try again when it finishes.",
      response.status,
      code,
      detail,
    );
  }
  if (
    response.status === 409 &&
    code === "duplicate_message"
  ) {
    throw new ChatApiError(
      "This message was already received. Conversation history is being refreshed.",
      response.status,
      code,
      detail,
    );
  }

  throw new ChatApiError(
    detail ?? `Chat API error: ${response.status} ${response.statusText}`,
    response.status,
    code,
    detail,
  );
}

export async function invokeChat(
  query: string,
  conversationId: string,
  clientMessageId: string,
  abortSignal: AbortSignal,
): Promise<ReadableStream<Uint8Array>> {
  const idToken = await getRequestToken();
  const headers = buildHeaders(idToken);
  const response = await sendChatRequest(
    query,
    conversationId,
    clientMessageId,
    abortSignal,
    headers,
  );

  if (!response.ok) {
    await throwResponseError(response);
  }
  if (!response.body) {
    throw new Error("No response body");
  }
  return response.body;
}

export async function cancelChat(
  conversationId: string,
  clientMessageId: string,
): Promise<void> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    CANCELLATION_TIMEOUT_MS,
  );
  try {
    const idToken = await getRequestToken();
    const response = await fetch(
      `/api/conversations/${encodeURIComponent(conversationId)}/invocations/${encodeURIComponent(clientMessageId)}/cancel`,
      {
        method: "POST",
        headers: buildHeaders(idToken, "application/json"),
        credentials: "same-origin",
        signal: controller.signal,
      },
    );
    if (!response.ok) {
      await throwResponseError(response);
    }
  } finally {
    window.clearTimeout(timeout);
  }
}
