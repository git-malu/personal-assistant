import type { ThreadMessage } from "@assistant-ui/react";
import { clearInboundAuthSession } from "@/lib/auth";
import { buildHeaders, getRequestToken } from "@/lib/chat/chat-api-client";

export type ConversationStatus = "active" | "archived";

interface ConversationWire {
  id: string;
  title: string;
  status: ConversationStatus;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

interface ConversationListWire {
  items: ConversationWire[];
  next_cursor: string | null;
}

interface TextPartWire {
  type: "text";
  text: string;
}

interface ConversationMessageWire {
  sequence: number;
  id: string;
  role: "user" | "assistant";
  content: {
    version: 1;
    parts: TextPartWire[];
  };
  client_message_id: string | null;
  reply_to_message_id: string | null;
  created_at: string;
}

interface ConversationMessageListWire {
  items: ConversationMessageWire[];
  next_cursor: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  status: ConversationStatus;
  createdAt: Date;
  updatedAt: Date;
  archivedAt: Date | null;
}

export interface ConversationPage {
  items: Conversation[];
  nextCursor?: string;
}

export interface ConversationHistory {
  headId: string | null;
  messages: Array<{
    message: ThreadMessage;
    parentId: string | null;
  }>;
}

export class ConversationApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ConversationApiError";
  }
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = await getRequestToken();
  const response = await fetch(path, {
    ...init,
    headers: {
      ...buildHeaders(token, "application/json"),
      ...init.headers,
    },
    credentials: "same-origin",
  });

  if (response.status === 401 || response.status === 403) {
    await clearInboundAuthSession();
    throw new ConversationApiError(
      "Authentication required. Please sign in.",
      response.status,
    );
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Preserve the HTTP status when an intermediary returned a non-JSON body.
    }
    throw new ConversationApiError(
      detail ?? `Conversation API error: ${response.status}`,
      response.status,
    );
  }

  return (await response.json()) as T;
}

async function requestEmpty(path: string, init: RequestInit): Promise<void> {
  const token = await getRequestToken();
  const response = await fetch(path, {
    ...init,
    headers: {
      ...buildHeaders(token, "application/json"),
      ...init.headers,
    },
    credentials: "same-origin",
  });
  if (response.status === 401 || response.status === 403) {
    await clearInboundAuthSession();
  }
  if (!response.ok) {
    throw new ConversationApiError(
      `Conversation API error: ${response.status}`,
      response.status,
    );
  }
}

function fromWire(item: ConversationWire): Conversation {
  return {
    id: item.id,
    title: item.title,
    status: item.status,
    createdAt: new Date(item.created_at),
    updatedAt: new Date(item.updated_at),
    archivedAt: item.archived_at ? new Date(item.archived_at) : null,
  };
}

export async function listConversations(
  status: ConversationStatus,
  cursor?: string,
  limit = 50,
  signal?: AbortSignal,
): Promise<ConversationPage> {
  const search = new URLSearchParams({ status, limit: String(limit) });
  if (cursor) search.set("cursor", cursor);
  const page = await requestJson<ConversationListWire>(
    `/api/conversations?${search}`,
    { signal },
  );
  return {
    items: page.items.map(fromWire),
    nextCursor: page.next_cursor ?? undefined,
  };
}

export async function createConversation(
  title?: string,
): Promise<Conversation> {
  const item = await requestJson<ConversationWire>("/api/conversations", {
    method: "POST",
    body: JSON.stringify(title ? { title } : {}),
  });
  return fromWire(item);
}

export async function getConversation(id: string): Promise<Conversation> {
  return fromWire(
    await requestJson<ConversationWire>(
      `/api/conversations/${encodeURIComponent(id)}`,
    ),
  );
}

export async function patchConversation(
  id: string,
  patch: { title?: string; status?: ConversationStatus },
): Promise<Conversation> {
  return fromWire(
    await requestJson<ConversationWire>(
      `/api/conversations/${encodeURIComponent(id)}`,
      { method: "PATCH", body: JSON.stringify(patch) },
    ),
  );
}

export async function deleteConversation(id: string): Promise<void> {
  await requestEmpty(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

function toThreadMessage(item: ConversationMessageWire): ThreadMessage {
  const content = item.content.parts.map((part) => ({
    type: "text" as const,
    text: part.text,
  }));
  const createdAt = new Date(item.created_at);
  if (item.role === "user") {
    return {
      id: item.id,
      role: "user",
      content,
      attachments: [],
      createdAt,
      metadata: { custom: {} },
    };
  }
  return {
    id: item.id,
    role: "assistant",
    content,
    createdAt,
    status: { type: "complete", reason: "stop" },
    metadata: {
      unstable_state: null,
      unstable_annotations: [],
      unstable_data: [],
      steps: [],
      custom: {},
    },
  };
}

export async function loadConversationHistory(
  conversationId: string,
): Promise<ConversationHistory> {
  const messages: ConversationMessageWire[] = [];
  let cursor: string | undefined;
  do {
    const search = new URLSearchParams({ limit: "100" });
    if (cursor) search.set("cursor", cursor);
    const page = await requestJson<ConversationMessageListWire>(
      `/api/conversations/${encodeURIComponent(conversationId)}/messages?${search}`,
    );
    messages.push(...page.items);
    cursor = page.next_cursor ?? undefined;
  } while (cursor);

  return {
    headId: messages.length > 0 ? messages[messages.length - 1]!.id : null,
    messages: messages.map((item, index) => ({
      message: toThreadMessage(item),
      parentId: index === 0 ? null : messages[index - 1]!.id,
    })),
  };
}
