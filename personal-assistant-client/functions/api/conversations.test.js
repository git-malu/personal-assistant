import { afterEach, describe, expect, it, vi } from "vitest";

import {
  onRequestGet as listConversations,
  onRequestPost as createConversation,
} from "./conversations.js";
import {
  onRequestPatch as patchConversation,
} from "./conversations/[conversation_id].js";
import {
  onRequestGet as listMessages,
} from "./conversations/[conversation_id]/messages.js";

describe("Conversation Pages Functions", () => {
  const originalFetch = globalThis.fetch;
  const runtimeSessionId = "123e4567-e89b-42d3-a456-426614174000";
  const conversationId = "6ee32f02-4c87-4c16-bcc8-cc69277ee42f";
  const env = {
    AGENTARTS_INVOCATIONS_URL:
      "https://runtime.example.com/runtimes/personal-assistant/invocations",
  };

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("allows only known list query parameters and controls identity headers", async () => {
    const mockFetch = vi.fn().mockResolvedValue(Response.json({ items: [] }));
    globalThis.fetch = mockFetch;
    const request = new Request(
      "https://app.example.com/api/conversations?status=active&limit=20&platform_admin=true",
      {
        headers: {
          Authorization: "Bearer jwt",
          Cookie: `pa_runtime_session=${runtimeSessionId}; raw=secret`,
          "x-hw-agentarts-session-id": "forged-session",
          "X-HW-AgentGateway-User-Id": "forged-user",
        },
      },
    );

    const response = await listConversations({ request, env });
    const forwarded = mockFetch.mock.calls[0][0];

    expect(forwarded.url).toBe(
      `${env.AGENTARTS_INVOCATIONS_URL}/api/conversations?status=active&limit=20`,
    );
    expect(forwarded.headers.get("x-hw-agentarts-session-id")).toBe(
      runtimeSessionId,
    );
    expect(forwarded.headers.get("X-HW-AgentGateway-User-Id")).toBeNull();
    expect(forwarded.headers.get("Cookie")).toBeNull();
    expect(response.status).toBe(200);
  });

  it("proxies create and item patch bodies to explicit paths", async () => {
    const mockFetch = vi.fn().mockResolvedValue(Response.json({ id: conversationId }));
    globalThis.fetch = mockFetch;

    await createConversation({
      request: new Request("https://app.example.com/api/conversations", {
        method: "POST",
        headers: {
          Cookie: `pa_runtime_session=${runtimeSessionId}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: "Notes" }),
      }),
      env,
    });
    await patchConversation({
      request: new Request(
        `https://app.example.com/api/conversations/${conversationId}`,
        {
          method: "PATCH",
          headers: {
            Cookie: `pa_runtime_session=${runtimeSessionId}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ status: "archived" }),
        },
      ),
      env,
      params: { conversation_id: conversationId },
    });

    expect(mockFetch.mock.calls[0][0].url).toBe(
      `${env.AGENTARTS_INVOCATIONS_URL}/api/conversations`,
    );
    expect(await mockFetch.mock.calls[0][0].json()).toEqual({ title: "Notes" });
    expect(mockFetch.mock.calls[1][0].url).toBe(
      `${env.AGENTARTS_INVOCATIONS_URL}/api/conversations/${conversationId}`,
    );
    expect(await mockFetch.mock.calls[1][0].json()).toEqual({
      status: "archived",
    });
  });

  it("allows only message pagination query parameters", async () => {
    const mockFetch = vi.fn().mockResolvedValue(Response.json({ items: [] }));
    globalThis.fetch = mockFetch;
    const request = new Request(
      `https://app.example.com/api/conversations/${conversationId}/messages?cursor=12&limit=50&debug=true`,
      { headers: { Cookie: `pa_runtime_session=${runtimeSessionId}` } },
    );

    await listMessages({
      request,
      env,
      params: { conversation_id: conversationId },
    });

    expect(mockFetch.mock.calls[0][0].url).toBe(
      `${env.AGENTARTS_INVOCATIONS_URL}/api/conversations/${conversationId}/messages?cursor=12&limit=50`,
    );
  });
});
