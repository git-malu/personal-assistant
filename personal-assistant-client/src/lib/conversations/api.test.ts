import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  deleteConversation,
  listConversations,
  loadConversationHistory,
} from "./api";
import { useAuthStore } from "@/stores/auth-store";

const { clearInboundAuthSession } = vi.hoisted(() => ({
  clearInboundAuthSession: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  acquireIdTokenSilently: vi.fn(),
  clearInboundAuthSession,
}));

const conversationWire = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Project notes",
  status: "active",
  created_at: "2026-07-15T08:00:00Z",
  updated_at: "2026-07-15T09:00:00Z",
  archived_at: null,
};

describe("Conversation API", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().clearToken();
    clearInboundAuthSession.mockReset();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("maps snake_case list data without sending platform-owned headers", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      Response.json({ items: [conversationWire], next_cursor: "next-page" }),
    );
    globalThis.fetch = mockFetch;

    const controller = new AbortController();
    const result = await listConversations(
      "active",
      undefined,
      25,
      controller.signal,
    );

    expect(result).toEqual({
      items: [
        {
          id: conversationWire.id,
          title: "Project notes",
          status: "active",
          createdAt: new Date(conversationWire.created_at),
          updatedAt: new Date(conversationWire.updated_at),
          archivedAt: null,
        },
      ],
      nextCursor: "next-page",
    });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/conversations?status=active&limit=25");
    expect(init.credentials).toBe("same-origin");
    expect(init.signal).toBe(controller.signal);
    expect(init.headers).not.toHaveProperty("x-hw-agentarts-session-id");
    expect(init.headers).not.toHaveProperty("X-HW-AgentGateway-User-Id");
  });

  it("loads every message page into one stable linear repository", async () => {
    const userMessage = {
      sequence: 1,
      id: "22222222-2222-4222-8222-222222222222",
      role: "user",
      content: { version: 1, parts: [{ type: "text", text: "Hello" }] },
      client_message_id: "33333333-3333-4333-8333-333333333333",
      reply_to_message_id: null,
      created_at: "2026-07-15T09:00:00Z",
    };
    const assistantMessage = {
      sequence: 2,
      id: "44444444-4444-4444-8444-444444444444",
      role: "assistant",
      content: { version: 1, parts: [{ type: "text", text: "Hi" }] },
      client_message_id: null,
      reply_to_message_id: userMessage.id,
      created_at: "2026-07-15T09:00:01Z",
    };
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ items: [userMessage], next_cursor: "1" }),
      )
      .mockResolvedValueOnce(
        Response.json({ items: [assistantMessage], next_cursor: null }),
      );
    globalThis.fetch = mockFetch;

    const history = await loadConversationHistory(conversationWire.id);

    expect(history.headId).toBe(assistantMessage.id);
    expect(history.messages.map((item) => item.parentId)).toEqual([
      null,
      userMessage.id,
    ]);
    expect(history.messages[0]?.message).toMatchObject({
      id: userMessage.id,
      role: "user",
      content: [{ type: "text", text: "Hello" }],
    });
    expect(history.messages[1]?.message).toMatchObject({
      id: assistantMessage.id,
      role: "assistant",
      status: { type: "complete", reason: "stop" },
      content: [{ type: "text", text: "Hi" }],
    });
    expect(mockFetch.mock.calls[1]?.[0]).toContain("cursor=1");
  });

  it("accepts a bodyless 204 delete response", async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    globalThis.fetch = mockFetch;

    await expect(deleteConversation(conversationWire.id)).resolves.toBeUndefined();

    expect(mockFetch).toHaveBeenCalledWith(
      `/api/conversations/${conversationWire.id}`,
      expect.objectContaining({ method: "DELETE", credentials: "same-origin" }),
    );
  });
});
