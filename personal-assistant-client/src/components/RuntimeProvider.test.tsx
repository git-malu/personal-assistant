import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const runtime = vi.hoisted(() => {
  const adapter = { run: vi.fn() };
  return {
    adapter,
    createChatAdapter: vi.fn(() => adapter),
    getThreadListItemState: vi.fn(),
    importHistory: vi.fn(),
    initialize: vi.fn(),
    loadConversationHistory: vi.fn(),
    threadListAdapter: { list: vi.fn() },
    createConversationThreadListAdapter: vi.fn(),
  };
});

vi.mock("../lib/chat-adapter", () => ({
  createChatAdapter: runtime.createChatAdapter,
}));

vi.mock("@/lib/conversations/api", () => ({
  loadConversationHistory: runtime.loadConversationHistory,
}));

vi.mock("@/lib/conversations/runtime", () => ({
  createConversationThreadListAdapter:
    runtime.createConversationThreadListAdapter,
}));

vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    thread: () => ({ import: runtime.importHistory }),
    threadListItem: () => ({
      getState: runtime.getThreadListItemState,
      initialize: runtime.initialize,
    }),
  }),
  useLocalRuntime: vi.fn((adapter) => adapter),
  useRemoteThreadListRuntime: vi.fn(
    ({ runtimeHook }: { runtimeHook: () => unknown }) => {
      runtimeHook();
      return {};
    },
  ),
  AssistantRuntimeProvider: ({ children }: { children: ReactNode }) => children,
}));

import { RuntimeProvider } from "./RuntimeProvider";

describe("RuntimeProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    runtime.createConversationThreadListAdapter.mockReturnValue(
      runtime.threadListAdapter,
    );
    runtime.getThreadListItemState.mockReturnValue({ remoteId: undefined });
    runtime.initialize.mockResolvedValue({
      remoteId: "11111111-1111-4111-8111-111111111111",
      externalId: "11111111-1111-4111-8111-111111111111",
    });
    runtime.loadConversationHistory.mockResolvedValue({
      headId: null,
      messages: [],
    });
  });

  it("renders children and wires the remote thread runtime", () => {
    render(
      <RuntimeProvider>
        <div data-testid="child">Hello World</div>
      </RuntimeProvider>,
    );

    expect(screen.getByTestId("child")).toHaveTextContent("Hello World");
    expect(runtime.createChatAdapter).toHaveBeenCalledOnce();
    expect(runtime.createConversationThreadListAdapter).toHaveBeenCalledOnce();
  });

  it("initializes a remote Conversation before the first Invocation", async () => {
    render(
      <RuntimeProvider>
        <span>Ready</span>
      </RuntimeProvider>,
    );
    const [resolveConversationId] = runtime.createChatAdapter.mock
      .calls[0] as unknown as [() => Promise<string>];

    await expect(resolveConversationId()).resolves.toBe(
      "11111111-1111-4111-8111-111111111111",
    );
    expect(runtime.initialize).toHaveBeenCalledOnce();
  });

  it("imports server history after a duplicate message response", async () => {
    const history = {
      headId: "message-1",
      messages: [{ message: { id: "message-1" }, parentId: null }],
    };
    runtime.loadConversationHistory.mockResolvedValue(history);
    render(
      <RuntimeProvider>
        <span>Ready</span>
      </RuntimeProvider>,
    );
    const [, onDuplicateMessage] = runtime.createChatAdapter.mock
      .calls[0] as unknown as [
      () => Promise<string>,
      (conversationId: string) => void,
    ];

    onDuplicateMessage("22222222-2222-4222-8222-222222222222");

    await waitFor(() => {
      expect(runtime.loadConversationHistory).toHaveBeenCalledWith(
        "22222222-2222-4222-8222-222222222222",
      );
      expect(runtime.importHistory).toHaveBeenCalledWith(history);
    });
  });
});
