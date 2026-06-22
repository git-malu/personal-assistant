import { acquireIdTokenSilently } from "@/lib/auth";
import { useAuthStore } from "@/stores/auth-store";
import { extractUserIdFromToken, isTokenExpiringSoon } from "./jwt";
import { getSessionId } from "./session";

function applyTokenHeaders(
  headers: Record<string, string>,
  idToken: string,
): void {
  headers.Authorization = `Bearer ${idToken}`;
  const userId = extractUserIdFromToken(idToken);
  if (userId) {
    headers["X-HW-AgentGateway-User-Id"] = userId;
  }
}

function buildHeaders(idToken: string | null): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    "Content-Type": "application/json",
    "x-hw-agentarts-session-id": getSessionId(),
  };
  if (idToken) {
    applyTokenHeaders(headers, idToken);
  }
  return headers;
}

function sendChatRequest(
  query: string,
  abortSignal: AbortSignal,
  headers: Record<string, string>,
  conversationId: string,
  clientMessageId: string,
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
  });
}

async function getRequestToken(): Promise<string | null> {
  let idToken = useAuthStore.getState().idToken;
  if (idToken && isTokenExpiringSoon(idToken)) {
    const freshToken = await acquireIdTokenSilently();
    if (freshToken) {
      useAuthStore.getState().setIdToken(freshToken);
      idToken = freshToken;
    }
  }
  return idToken;
}

function throwResponseError(response: Response): never {
  if (response.status === 401 || response.status === 403) {
    useAuthStore.getState().clearToken();
    throw new Error("Authentication required. Please sign in.");
  }
  throw new Error(`Chat API error: ${response.status} ${response.statusText}`);
}

export async function invokeChat(
  query: string,
  abortSignal: AbortSignal,
  conversationId: string = getSessionId(),
  clientMessageId: string = crypto.randomUUID(),
): Promise<ReadableStream<Uint8Array>> {
  const idToken = await getRequestToken();
  const headers = buildHeaders(idToken);
  let response = await sendChatRequest(
    query,
    abortSignal,
    headers,
    conversationId,
    clientMessageId,
  );

  if ((response.status === 401 || response.status === 403) && idToken) {
    const freshToken = await acquireIdTokenSilently();
    if (!freshToken) {
      useAuthStore.getState().clearToken();
      throw new Error("Authentication required. Please sign in.");
    }

    useAuthStore.getState().setIdToken(freshToken);
    applyTokenHeaders(headers, freshToken);
    response = await sendChatRequest(
      query,
      abortSignal,
      headers,
      conversationId,
      clientMessageId,
    );
  }

  if (!response.ok) {
    throwResponseError(response);
  }
  if (!response.body) {
    throw new Error("No response body");
  }
  return response.body;
}
