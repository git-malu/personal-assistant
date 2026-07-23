import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  AssistantRuntimeProvider,
  useAui,
  useAuiState,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  type ChatModelAdapter,
} from "@assistant-ui/react";
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

const conversation = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "New conversation",
  status: "active" as const,
  createdAt: new Date("2026-07-21T08:00:00Z"),
  updatedAt: new Date("2026-07-21T08:00:00Z"),
  archivedAt: null,
};

const modelAdapter: ChatModelAdapter = {
  async *run() {
    yield { content: [{ type: "text", text: "ok" }] };
  },
};

function useThreadRuntime() {
  return useLocalRuntime(modelAdapter);
}

function StateProbe() {
  const aui = useAui();
  const threadCount = useAuiState((state) => state.threads.threadIds.length);
  return (
    <>
      <button
        type="button"
        onClick={() => void aui.threadListItem().initialize()}
      >
        Initialize
      </button>
      <button type="button" onClick={() => void aui.threads().reload()}>
        Reload
      </button>
      <output data-testid="thread-count">{threadCount}</output>
    </>
  );
}

describe("Conversation runtime initialization ordering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps the first initialized thread when the initial empty list finishes", async () => {
    let resolveActive!: (value: { items: []; nextCursor: undefined }) => void;
    let resolveArchived!: (value: { items: []; nextCursor: undefined }) => void;
    api.listConversations.mockImplementation((status: string) =>
      new Promise((resolve) => {
        if (status === "active") resolveActive = resolve;
        else resolveArchived = resolve;
      }),
    );
    api.createConversation.mockResolvedValue(conversation);
    const threadListAdapter = createConversationThreadListAdapter();

    function Harness() {
      const runtime = useRemoteThreadListRuntime({
        runtimeHook: useThreadRuntime,
        adapter: threadListAdapter,
      });
      return (
        <AssistantRuntimeProvider runtime={runtime}>
          <StateProbe />
        </AssistantRuntimeProvider>
      );
    }

    render(<Harness />);
    await waitFor(() => expect(api.listConversations).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: "Initialize" }));
    await waitFor(() =>
      expect(screen.getByTestId("thread-count")).toHaveTextContent("1"),
    );
    expect(api.createConversation).not.toHaveBeenCalled();

    await act(async () => {
      resolveActive({ items: [], nextCursor: undefined });
      resolveArchived({ items: [], nextCursor: undefined });
    });

    await waitFor(() => expect(api.createConversation).toHaveBeenCalledOnce());
    expect(screen.getByTestId("thread-count")).toHaveTextContent("1");
  });

  it("waits for a retry list before initializing the first thread", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    let resolveActive!: (value: { items: []; nextCursor: undefined }) => void;
    let resolveArchived!: (value: { items: []; nextCursor: undefined }) => void;
    api.listConversations
      .mockRejectedValueOnce(new Error("initial list unavailable"))
      .mockRejectedValueOnce(new Error("initial list unavailable"))
      .mockImplementation((status: string) =>
        new Promise((resolve) => {
          if (status === "active") resolveActive = resolve;
          else resolveArchived = resolve;
        }),
      );
    api.createConversation.mockResolvedValue(conversation);
    const threadListAdapter = createConversationThreadListAdapter();

    function Harness() {
      const runtime = useRemoteThreadListRuntime({
        runtimeHook: useThreadRuntime,
        adapter: threadListAdapter,
      });
      return (
        <AssistantRuntimeProvider runtime={runtime}>
          <StateProbe />
        </AssistantRuntimeProvider>
      );
    }

    try {
      render(<Harness />);
      await waitFor(() => expect(api.listConversations).toHaveBeenCalledTimes(2));

      fireEvent.click(screen.getByRole("button", { name: "Reload" }));
      await waitFor(() => expect(api.listConversations).toHaveBeenCalledTimes(4));
      fireEvent.click(screen.getByRole("button", { name: "Initialize" }));

      expect(api.createConversation).not.toHaveBeenCalled();
      await act(async () => {
        resolveActive({ items: [], nextCursor: undefined });
        resolveArchived({ items: [], nextCursor: undefined });
      });

      await waitFor(() => expect(api.createConversation).toHaveBeenCalledOnce());
      expect(screen.getByTestId("thread-count")).toHaveTextContent("1");
      expect(consoleError).toHaveBeenCalledWith(
        "[assistant-ui] thread list load failed:",
        expect.any(Error),
      );
    } finally {
      consoleError.mockRestore();
    }
  });
});
