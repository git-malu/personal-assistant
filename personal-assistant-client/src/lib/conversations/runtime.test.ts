import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
  getConversation: vi.fn(),
  listConversations: vi.fn(),
  loadConversationHistory: vi.fn(),
  patchConversation: vi.fn(),
}));

vi.mock("./api", () => api);

import { createConversationThreadListAdapter } from "./runtime";
import { useConversationListStore } from "@/stores/conversation-list-store";

const active = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Active",
  status: "active" as const,
  createdAt: new Date("2026-07-15T08:00:00Z"),
  updatedAt: new Date("2026-07-15T09:00:00Z"),
  archivedAt: null,
};

const archived = {
  ...active,
  id: "22222222-2222-4222-8222-222222222222",
  title: "Archived",
  status: "archived" as const,
  archivedAt: new Date("2026-07-15T09:00:00Z"),
};

describe("Conversation remote thread adapter", () => {
  let adapter: ReturnType<typeof createConversationThreadListAdapter>;

  beforeEach(() => {
    vi.clearAllMocks();
    useConversationListStore.getState().setError(null);
    adapter = createConversationThreadListAdapter();
  });

  it("merges active and archived pages and preserves both cursors", async () => {
    api.listConversations
      .mockResolvedValueOnce({ items: [active], nextCursor: "active-next" })
      .mockResolvedValueOnce({ items: [archived], nextCursor: undefined })
      .mockResolvedValueOnce({ items: [], nextCursor: undefined });

    const first = await adapter.list();
    const second = await adapter.list({
      after: first.nextCursor,
    });

    expect(first.threads).toEqual([
      expect.objectContaining({
        status: "regular",
        remoteId: active.id,
        externalId: active.id,
      }),
      expect.objectContaining({
        status: "archived",
        remoteId: archived.id,
        externalId: archived.id,
      }),
    ]);
    expect(first.nextCursor).toEqual(expect.any(String));
    expect(second.nextCursor).toBeUndefined();
    expect(api.listConversations).toHaveBeenNthCalledWith(
      3,
      "active",
      "active-next",
      50,
      undefined,
    );
  });

  it("maps initialize and Conversation mutations to the API", async () => {
    api.createConversation.mockResolvedValue(active);
    api.getConversation.mockResolvedValue(archived);

    await expect(
      adapter.initialize("local-thread"),
    ).resolves.toEqual({ remoteId: active.id, externalId: active.id });
    await adapter.rename(active.id, "Renamed");
    await adapter.archive(active.id);
    await adapter.unarchive(active.id);
    await adapter.delete(active.id);
    await expect(adapter.fetch(archived.id)).resolves.toEqual(
      expect.objectContaining({
        status: "archived",
        remoteId: archived.id,
        externalId: archived.id,
      }),
    );

    expect(api.patchConversation).toHaveBeenCalledWith(active.id, {
      title: "Renamed",
    });
    expect(api.patchConversation).toHaveBeenCalledWith(active.id, {
      status: "archived",
    });
    expect(api.patchConversation).toHaveBeenCalledWith(active.id, {
      status: "active",
    });
    expect(api.deleteConversation).toHaveBeenCalledWith(active.id);
  });

  it("waits for the initial list to settle before creating a Conversation", async () => {
    let resolveActive!: (value: { items: []; nextCursor: undefined }) => void;
    let resolveArchived!: (value: { items: []; nextCursor: undefined }) => void;
    api.listConversations.mockImplementation((status: string) =>
      new Promise((resolve) => {
        if (status === "active") resolveActive = resolve;
        else resolveArchived = resolve;
      }),
    );
    api.createConversation.mockResolvedValue(active);

    const list = adapter.list();
    const initialize = adapter.initialize("local-thread");

    expect(api.createConversation).not.toHaveBeenCalled();
    resolveActive({ items: [], nextCursor: undefined });
    resolveArchived({ items: [], nextCursor: undefined });

    await list;
    await expect(initialize).resolves.toEqual({
      remoteId: active.id,
      externalId: active.id,
    });
    expect(api.createConversation).toHaveBeenCalledOnce();
  });

  it("allows initialization after the initial list fails", async () => {
    api.listConversations.mockRejectedValue(new Error("list unavailable"));
    api.createConversation.mockResolvedValue(active);

    const list = adapter.list();
    const initialize = adapter.initialize("local-thread");

    await expect(list).rejects.toThrow("list unavailable");
    await expect(initialize).resolves.toEqual({
      remoteId: active.id,
      externalId: active.id,
    });
  });

  it("allows initialization after a list timeout", async () => {
    vi.useFakeTimers();
    try {
      const signals: AbortSignal[] = [];
      api.listConversations.mockImplementation(
        (
          _status: string,
          _cursor: string | undefined,
          _limit: number,
          signal: AbortSignal,
        ) => {
          signals.push(signal);
          return new Promise(() => {});
        },
      );
      api.createConversation.mockResolvedValue(active);

      const list = adapter.list();
      const listResult = expect(list).rejects.toThrow(
        "Conversations could not be loaded.",
      );
      const initialize = adapter.initialize("local-thread");

      expect(api.createConversation).not.toHaveBeenCalled();
      await vi.runOnlyPendingTimersAsync();

      await listResult;
      expect(signals).toHaveLength(2);
      expect(signals.every((signal) => signal.aborted)).toBe(true);
      await expect(initialize).resolves.toEqual({
        remoteId: active.id,
        externalId: active.id,
      });
      expect(useConversationListStore.getState().error).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("exposes a retryable error when a list times out without a send", async () => {
    vi.useFakeTimers();
    try {
      api.listConversations.mockImplementation(() => new Promise(() => {}));

      const list = adapter.list();
      const listResult = expect(list).rejects.toThrow(
        "Conversations could not be loaded.",
      );
      await vi.runOnlyPendingTimersAsync();

      await listResult;
      expect(useConversationListStore.getState().error).toBe(
        "Conversations could not be loaded.",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("ignores a stale list failure after a successful retry", async () => {
    vi.useFakeTimers();
    try {
      let rejectStale!: (error: Error) => void;
      api.listConversations
        .mockImplementationOnce(
          () =>
            new Promise((_, reject) => {
              rejectStale = reject;
            }),
        )
        .mockImplementationOnce(() => new Promise(() => {}))
        .mockResolvedValue({ items: [], nextCursor: undefined });

      const stale = adapter.list();
      const staleResult = expect(stale).rejects.toThrow(
        "Conversations could not be loaded.",
      );
      await vi.runOnlyPendingTimersAsync();
      await staleResult;

      await adapter.list();
      expect(useConversationListStore.getState().error).toBeNull();

      rejectStale(new Error("late stale failure"));
      await Promise.resolve();
      expect(useConversationListStore.getState().error).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
