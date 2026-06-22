import { describe, expect, it, vi } from "vitest";
import { onRequestGet, onRequestPost } from "./index.js";

function env(store) {
  return { ALLOW_DEV_AUTH: "true", CONVERSATION_STORE: store };
}

describe("Conversation BFF", () => {
  it("lists only through the authenticated user scope", async () => {
    const store = {
      listConversations: vi.fn().mockResolvedValue({
        conversations: [{ id: "conversation-1", title: "Trip" }],
      }),
    };
    const request = new Request("https://example.com/api/conversations", {
      headers: { "x-hw-agentgateway-user-id": "user-1" },
    });
    const response = await onRequestGet({ request, env: env(store) });

    expect(response.status).toBe(200);
    expect(store.listConversations).toHaveBeenCalledWith(
      "user-1",
      expect.objectContaining({ status: "all" }),
    );
  });

  it("creates idempotently with the request key", async () => {
    const store = {
      createConversation: vi.fn().mockResolvedValue({
        id: "conversation-1",
        title: "新对话",
      }),
    };
    const request = new Request("https://example.com/api/conversations", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "idempotency-key": "request-1",
        "x-hw-agentgateway-user-id": "user-1",
      },
      body: "{}",
    });
    const response = await onRequestPost({ request, env: env(store) });

    expect(response.status).toBe(201);
    expect(store.createConversation).toHaveBeenCalledWith(
      "user-1",
      expect.objectContaining({ idempotencyKey: "request-1" }),
    );
  });
});
