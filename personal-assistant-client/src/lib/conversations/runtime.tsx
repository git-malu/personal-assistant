import {
  RuntimeAdapterProvider,
  useAuiState,
  type RemoteThreadListAdapter,
  type ThreadHistoryAdapter,
  type ThreadMessage,
} from "@assistant-ui/react";
import { type PropsWithChildren, useMemo } from "react";
import { useConversationListStore } from "@/stores/conversation-list-store";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  loadConversationHistory,
  patchConversation,
} from "./api";

interface PageCursor {
  active?: string;
  archived?: string;
  activeDone?: boolean;
  archivedDone?: boolean;
}

type ConversationThreadListAdapter = Omit<RemoteThreadListAdapter, "list"> & {
  list(
    options?: Parameters<RemoteThreadListAdapter["list"]>[0],
    signal?: AbortSignal,
  ): ReturnType<RemoteThreadListAdapter["list"]>;
};

const CONVERSATION_LIST_TIMEOUT_MS = 15_000;
const CONVERSATION_LIST_ERROR = "Conversations could not be loaded.";

function settle(promise: Promise<unknown>): Promise<void> {
  return promise.then(
    () => undefined,
    () => undefined,
  );
}

function afterSettled<T>(
  preceding: Promise<void> | undefined,
  run: () => Promise<T>,
): Promise<T> {
  return preceding ? preceding.then(run) : run();
}

function setConversationListError(error: unknown): void {
  useConversationListStore
    .getState()
    .setError(
      error instanceof Error ? error.message : CONVERSATION_LIST_ERROR,
    );
}

function withConversationListTimeout<T>(
  run: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const request = run(controller.signal);
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      controller.abort();
      reject(new Error(CONVERSATION_LIST_ERROR));
    }, CONVERSATION_LIST_TIMEOUT_MS);

    void request.then(
      (value) => {
        window.clearTimeout(timeout);
        resolve(value);
      },
      (error: unknown) => {
        window.clearTimeout(timeout);
        reject(error);
      },
    );
  });
}

function encodePageCursor(cursor: PageCursor): string {
  return encodeURIComponent(JSON.stringify(cursor));
}

function decodePageCursor(value: string | undefined): PageCursor {
  if (!value) return {};
  try {
    const parsed = JSON.parse(decodeURIComponent(value)) as PageCursor;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function firstUserTitle(messages: readonly ThreadMessage[]): string {
  const text = messages
    .find((message) => message.role === "user")
    ?.content.find((part) => part.type === "text")?.text;
  return text?.trim().replace(/\s+/g, " ").slice(0, 60) || "新对话";
}

function createHistoryAdapter(
  conversationId: string | undefined,
): ThreadHistoryAdapter {
  return {
    async load() {
      if (!conversationId) return { headId: null, messages: [] };
      return loadConversationHistory(conversationId);
    },
    async append() {
      // InvocationService is the only writer for durable messages.
    },
  };
}

function ConversationThreadProvider({ children }: PropsWithChildren) {
  const conversationId = useAuiState(
    (state) => state.threadListItem.remoteId,
  );
  const history = useMemo(
    () => createHistoryAdapter(conversationId),
    [conversationId],
  );
  const adapters = useMemo(() => ({ history }), [history]);
  return (
    <RuntimeAdapterProvider adapters={adapters}>
      {children}
    </RuntimeAdapterProvider>
  );
}

const conversationThreadListAdapter: ConversationThreadListAdapter = {
  async list(options, signal) {
    useConversationListStore.getState().setError(null);
    try {
      const cursor = decodePageCursor(options?.after);
      const [active, archived] = await Promise.all([
        cursor.activeDone
          ? Promise.resolve({ items: [], nextCursor: undefined })
          : listConversations("active", cursor.active, 50, signal),
        cursor.archivedDone
          ? Promise.resolve({ items: [], nextCursor: undefined })
          : listConversations("archived", cursor.archived, 50, signal),
      ]);
      const next: PageCursor = {
        active: active.nextCursor,
        archived: archived.nextCursor,
        activeDone: !active.nextCursor,
        archivedDone: !archived.nextCursor,
      };
      const hasMore = !next.activeDone || !next.archivedDone;

      return {
        threads: [...active.items, ...archived.items].map((item) => ({
          status: item.status === "archived" ? "archived" : "regular",
          remoteId: item.id,
          externalId: item.id,
          title: item.title,
          lastMessageAt: item.updatedAt,
        })),
        nextCursor: hasMore ? encodePageCursor(next) : undefined,
      };
    } catch (error) {
      throw error;
    }
  },
  async initialize() {
    const conversation = await createConversation();
    return { remoteId: conversation.id, externalId: conversation.id };
  },
  async rename(remoteId, newTitle) {
    await patchConversation(remoteId, { title: newTitle });
  },
  async archive(remoteId) {
    await patchConversation(remoteId, { status: "archived" });
  },
  async unarchive(remoteId) {
    await patchConversation(remoteId, { status: "active" });
  },
  delete: deleteConversation,
  async fetch(remoteId) {
    const item = await getConversation(remoteId);
    return {
      status: item.status === "archived" ? "archived" : "regular",
      remoteId: item.id,
      externalId: item.id,
      title: item.title,
      lastMessageAt: item.updatedAt,
    };
  },
  async generateTitle(remoteId, messages) {
    const title = firstUserTitle(messages);
    await patchConversation(remoteId, { title });
    return new ReadableStream({
      start(controller) {
        controller.enqueue({
          type: "part-start",
          path: [0],
          part: { type: "text" },
        });
        controller.enqueue({ type: "text-delta", path: [0], textDelta: title });
        controller.enqueue({ type: "part-finish", path: [0] });
        controller.close();
      },
    });
  },
  unstable_Provider: ConversationThreadProvider,
};

export function createConversationThreadListAdapter(): RemoteThreadListAdapter {
  let currentFullListSettled: Promise<void> | undefined;
  let currentFullListToken: symbol | undefined;

  return {
    ...conversationThreadListAdapter,
    list(options) {
      if (options?.after) {
        const request = conversationThreadListAdapter.list(options);
        void request.catch(setConversationListError);
        return request;
      }

      const token = Symbol("full-list");
      currentFullListToken = token;
      const request = withConversationListTimeout((signal) =>
        conversationThreadListAdapter.list(options, signal),
      );
      void request.then(
        () => undefined,
        (error: unknown) => {
          if (currentFullListToken !== token) return;
          setConversationListError(error);
        },
      );
      currentFullListSettled = settle(request);
      return request;
    },
    initialize(threadId) {
      const precedingFullList = currentFullListSettled;
      const request = afterSettled(precedingFullList, () => {
        useConversationListStore.getState().setError(null);
        return conversationThreadListAdapter.initialize(threadId);
      });
      return request;
    },
  };
}
