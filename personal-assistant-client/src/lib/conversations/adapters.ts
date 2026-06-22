import type {
  ExportedMessageRepository,
  ExportedMessageRepositoryItem,
  RemoteThreadListAdapter,
  ThreadHistoryAdapter,
  ThreadMessage,
} from "@assistant-ui/react";
import type { AssistantStream, AssistantStreamChunk } from "assistant-stream";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  listMessages,
  updateConversation,
} from "./api";

function metadata(conversation: Awaited<ReturnType<typeof getConversation>>) {
  return {
    status: conversation.status,
    remoteId: conversation.id,
    title: conversation.title,
    lastMessageAt: new Date(conversation.updated_at),
  } as const;
}

export const conversationListAdapter: RemoteThreadListAdapter = {
  async list({ after } = {}) {
    const page = await listConversations(after);
    return {
      threads: page.conversations.map(metadata),
      nextCursor: page.next_cursor,
    };
  },
  async initialize() {
    const conversation = await createConversation();
    return { remoteId: conversation.id, externalId: undefined };
  },
  async fetch(_threadId) {
    return metadata(await getConversation(_threadId));
  },
  async rename(remoteId, newTitle) {
    await updateConversation(remoteId, { title: newTitle });
  },
  async archive(remoteId) {
    await updateConversation(remoteId, { status: "archived" });
  },
  async unarchive(remoteId) {
    await updateConversation(remoteId, { status: "regular" });
  },
  async delete(remoteId) {
    await deleteConversation(remoteId);
  },
  async generateTitle(remoteId, messages) {
    const firstUser = messages.find((message) => message.role === "user");
    const titlePart = firstUser?.content.find((part) => part.type === "text");
    const title =
      titlePart?.type === "text"
        ? titlePart.text.trim().slice(0, 36) || "新对话"
        : "新对话";
    await updateConversation(remoteId, { title });
    return new ReadableStream<AssistantStreamChunk>() as AssistantStream;
  },
};

function toThreadMessage(message: Awaited<ReturnType<typeof listMessages>>["messages"][number]) {
  const common = {
    id: message.id,
    createdAt: new Date(message.created_at),
    role: message.role,
    content: message.content,
  };
  if (message.role === "assistant") {
    return {
      ...common,
      role: "assistant" as const,
      status: { type: "complete" as const, reason: "stop" as const },
      metadata: {
        unstable_state: null,
        unstable_annotations: [],
        unstable_data: [],
        steps: [],
        custom: {},
      },
    } satisfies ThreadMessage;
  }
  if (message.role === "user") {
    return {
      ...common,
      role: "user" as const,
      attachments: [],
      metadata: { custom: {} },
    } satisfies ThreadMessage;
  }
  return {
    ...common,
    role: "system" as const,
    content: [message.content[0] ?? { type: "text", text: "" }],
    metadata: { custom: {} },
  } satisfies ThreadMessage;
}

export function createHistoryAdapter(
  conversationId: string | undefined,
): ThreadHistoryAdapter {
  return {
    async load(): Promise<ExportedMessageRepository> {
      if (!conversationId) return { messages: [] };
      const page = await listMessages(conversationId);
      return {
        headId: page.messages[page.messages.length - 1]?.id ?? null,
        messages: page.messages.map((message) => ({
          parentId: message.parent_id,
          message: toThreadMessage(message),
        })),
      };
    },
    async append(_item: ExportedMessageRepositoryItem) {
      // Invocation BFF persists user + trusted assistant messages atomically
      // around the SSE execution boundary.
    },
  };
}
