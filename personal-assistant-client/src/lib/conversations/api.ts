import { acquireIdTokenSilently } from "@/lib/auth";
import { useAuthStore } from "@/stores/auth-store";

export type Conversation = {
  id: string;
  title: string;
  status: "regular" | "archived";
  version: number;
  created_at: string;
  updated_at: string;
};

export type ConversationMessage = {
  id: string;
  parent_id: string | null;
  role: "user" | "assistant" | "system";
  content: Array<{ type: "text"; text: string }>;
  sequence: number;
  status: "pending" | "complete" | "failed" | "uncertain";
  created_at: string;
};

const DEV_CONVERSATIONS_KEY = "pa-dev-conversations";

function devConversations(): Conversation[] {
  try {
    return JSON.parse(localStorage.getItem(DEV_CONVERSATIONS_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveDevConversations(conversations: Conversation[]) {
  localStorage.setItem(DEV_CONVERSATIONS_KEY, JSON.stringify(conversations));
}

async function authorizedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  let token = useAuthStore.getState().idToken;
  if (!token) token = await acquireIdTokenSilently();
  const headers = new Headers(init.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401 || response.status === 403) {
    useAuthStore.getState().clearToken();
  }
  return response;
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Conversation API error: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function listConversations(after?: string) {
  if (import.meta.env.DEV) {
    return { conversations: devConversations(), next_cursor: undefined };
  }
  const query = after ? `?after=${encodeURIComponent(after)}` : "";
  return json<{ conversations: Conversation[]; next_cursor?: string }>(
    await authorizedFetch(`/api/conversations${query}`),
  );
}

export async function createConversation() {
  if (import.meta.env.DEV) {
    const now = new Date().toISOString();
    const conversation: Conversation = {
      id: crypto.randomUUID(),
      title: "新对话",
      status: "regular",
      version: 1,
      created_at: now,
      updated_at: now,
    };
    saveDevConversations([conversation, ...devConversations()]);
    return conversation;
  }
  return json<Conversation>(
    await authorizedFetch("/api/conversations", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "idempotency-key": crypto.randomUUID(),
      },
      body: "{}",
    }),
  );
}

export async function getConversation(id: string) {
  if (import.meta.env.DEV) {
    const conversation = devConversations().find((item) => item.id === id);
    if (!conversation) throw new Error("Conversation not found");
    return conversation;
  }
  return json<Conversation>(
    await authorizedFetch(`/api/conversations/${id}`),
  );
}

export async function updateConversation(
  id: string,
  patch: { title?: string; status?: "regular" | "archived" },
) {
  if (import.meta.env.DEV) {
    let updated: Conversation | undefined;
    const conversations = devConversations().map((conversation) => {
      if (conversation.id !== id) return conversation;
      updated = {
        ...conversation,
        ...patch,
        version: conversation.version + 1,
        updated_at: new Date().toISOString(),
      };
      return updated;
    });
    saveDevConversations(conversations);
    if (!updated) throw new Error("Conversation not found");
    return updated;
  }
  return json<Conversation>(
    await authorizedFetch(`/api/conversations/${id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    }),
  );
}

export async function deleteConversation(id: string) {
  if (import.meta.env.DEV) {
    saveDevConversations(
      devConversations().filter((conversation) => conversation.id !== id),
    );
    return;
  }
  const response = await authorizedFetch(`/api/conversations/${id}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 404) {
    throw new Error(`Conversation API error: ${response.status}`);
  }
}

export async function listMessages(id: string) {
  if (import.meta.env.DEV) {
    return { messages: [], next_cursor: undefined };
  }
  return json<{ messages: ConversationMessage[]; next_cursor?: string }>(
    await authorizedFetch(`/api/conversations/${id}/messages`),
  );
}

export async function ensureRuntimeSession() {
  if (import.meta.env.DEV) return { status: "ready" as const };
  return json<{ status: "warming" | "ready" | "degraded" }>(
    await authorizedFetch("/api/runtime-session/ensure", { method: "POST" }),
  );
}

export async function migrateLegacyConversation(legacySessionId: string) {
  if (import.meta.env.DEV) return { migrated: false };
  return json<{ conversation_id?: string; migrated: boolean }>(
    await authorizedFetch("/api/legacy-conversation-migrations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ legacy_session_id: legacySessionId }),
    }),
  );
}
