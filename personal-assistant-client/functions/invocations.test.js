import { afterEach, describe, expect, it, vi } from "vitest";

import { onRequestPost } from "./invocations.js";

describe("Cloudflare Pages invocations proxy", () => {
  const originalFetch = globalThis.fetch;
  const env = {
    AGENTARTS_INVOCATIONS_URL:
      "https://runtime.example.com/runtimes/personal-assistant/invocations",
  };

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("forwards the request to the full AgentArts Runtime path", async () => {
    const upstreamBody = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: token\n\n"));
        controller.close();
      },
    });
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(upstreamBody, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    globalThis.fetch = mockFetch;

    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/invocations",
      {
        method: "POST",
        headers: {
          Authorization: "Bearer test-jwt",
          Cookie: "should-not-be-forwarded=true",
          "Content-Type": "application/json",
          "x-hw-agentarts-session-id": "test-session",
        },
        body: JSON.stringify({ message: "hello", stream: true }),
      },
    );

    const response = await onRequestPost({ request, env });
    const forwardedRequest = mockFetch.mock.calls[0][0];

    expect(forwardedRequest.url).toBe(
      env.AGENTARTS_INVOCATIONS_URL,
    );
    expect(forwardedRequest.headers.get("Authorization")).toBe(
      "Bearer test-jwt",
    );
    expect(forwardedRequest.headers.get("x-hw-agentarts-session-id")).toBe(
      "test-session",
    );
    expect(forwardedRequest.headers.get("Cookie")).toBeNull();
    expect(await forwardedRequest.json()).toEqual({
      message: "hello",
      stream: true,
    });
    expect(response.headers.get("Content-Type")).toContain("text/event-stream");
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.text()).toBe("data: token\n\n");
  });

  it("returns 502 when the Gateway request fails", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error("network error"));

    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/invocations",
      {
        method: "POST",
        body: "{}",
      },
    );

    const response = await onRequestPost({ request, env });

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      message: "AgentArts Gateway is unavailable",
    });
  });

  it("fails clearly when the upstream URL is not configured", async () => {
    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/invocations",
      {
        method: "POST",
        body: "{}",
      },
    );

    const response = await onRequestPost({ request, env: {} });

    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({
      message: "Frontend proxy is not configured",
    });
  });

  it("uses the user active Runtime lease for a Conversation invocation", async () => {
    const upstreamBody = new ReadableStream({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"token":"hello","done":false}\n\n' +
              'data: {"token":"","done":true}\n\n',
          ),
        );
        controller.close();
      },
    });
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(upstreamBody, {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );
    globalThis.fetch = mockFetch;
    const store = {
      getConversation: vi.fn().mockResolvedValue({ id: "conversation-1" }),
      getActiveLease: vi.fn().mockResolvedValue({
        runtime_session_id: "runtime-user-1",
      }),
      appendMessage: vi.fn().mockResolvedValue({}),
    };
    const tasks = [];
    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/invocations",
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-hw-agentgateway-user-id": "user-1",
        },
        body: JSON.stringify({
          conversation_id: "conversation-1",
          client_message_id: "11111111-1111-4111-8111-111111111111",
          message: "hello",
          stream: true,
        }),
      },
    );
    const response = await onRequestPost({
      request,
      env: {
        ...env,
        ALLOW_DEV_AUTH: "true",
        CONVERSATION_STORE: store,
      },
      waitUntil: (task) => tasks.push(task),
    });
    await response.text();
    await Promise.all(tasks);

    const forwarded = mockFetch.mock.calls[0][0];
    expect(forwarded.headers.get("x-hw-agentarts-session-id")).toBe(
      "runtime-user-1",
    );
    expect(store.getConversation).toHaveBeenCalledWith(
      "user-1",
      "conversation-1",
    );
    expect(store.appendMessage).toHaveBeenCalledTimes(2);
  });
});
