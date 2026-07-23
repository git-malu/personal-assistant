import { afterEach, describe, expect, it, vi } from "vitest";

import { onRequestPost as onRequestPostRoot } from "./invocations.js";
import { onRequestPost as onRequestPostCancellation } from "./api/conversations/[conversation_id]/invocations/[client_message_id]/cancel.js";
import {
  buildCallbackUpstreamUrl,
  onRequestGet as onRequestGetCalendarCallback,
} from "./auth/callback/m365-calendar.js";

describe("Cloudflare Pages invocations proxy", () => {
  const originalFetch = globalThis.fetch;
  const runtimeSessionId = "123e4567-e89b-42d3-a456-426614174000";
  const env = {
    AGENTARTS_INVOCATIONS_URL:
      "https://runtime.example.com/runtimes/personal-assistant/invocations",
  };

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("forwards the request to the full AgentArts Runtime path", async () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(runtimeSessionId);
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
          "x-hw-agentarts-session-id": "forged-session",
          "X-HW-AgentGateway-User-Id": "forged-user",
        },
        body: JSON.stringify({ message: "hello", stream: true }),
      },
    );

    const response = await onRequestPostRoot({ request, env });
    const forwardedRequest = mockFetch.mock.calls[0][0];

    expect(forwardedRequest.url).toBe(
      env.AGENTARTS_INVOCATIONS_URL,
    );
    expect(forwardedRequest.headers.get("Authorization")).toBe(
      "Bearer test-jwt",
    );
    expect(forwardedRequest.headers.get("x-hw-agentarts-session-id")).toBe(
      runtimeSessionId,
    );
    expect(
      forwardedRequest.headers.get("X-HW-AgentGateway-User-Id"),
    ).toBeNull();
    expect(forwardedRequest.headers.get("Cookie")).toBeNull();
    expect(await forwardedRequest.json()).toEqual({
      message: "hello",
      stream: true,
    });
    expect(response.headers.get("Content-Type")).toContain("text/event-stream");
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(response.headers.get("Set-Cookie")).toContain(
      "pa_oauth2_callback_auth=Bearer%20test-jwt",
    );
    expect(response.headers.get("Set-Cookie")).toContain(
      `pa_oauth2_callback_session=${runtimeSessionId}`,
    );
    expect(response.headers.get("Set-Cookie")).toContain(
      `pa_runtime_session=${runtimeSessionId}`,
    );
    expect(response.headers.get("Set-Cookie")).not.toContain(
      "pa_oauth2_callback_user=forged-user",
    );
    expect(response.headers.get("Set-Cookie")).toContain("HttpOnly");
    expect(response.headers.get("Set-Cookie")).toContain("SameSite=Lax");
    expect(await response.text()).toBe("data: token\n\n");
  });

  it("adds the direct Service invocation path in local Pages mode", async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response("ok"));
    globalThis.fetch = mockFetch;
    const request = new Request("http://localhost:5173/invocations", {
      method: "POST",
      body: "{}",
    });

    await onRequestPostRoot({
      request,
      env: {
        PA_ENV: "local",
        AGENTARTS_INVOCATIONS_URL: "http://localhost:8080",
      },
    });

    expect(mockFetch.mock.calls[0][0].url).toBe(
      "http://localhost:8080/invocations",
    );
  });

  it("forwards explicit invocation cancellation through the Gateway suffix path", async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    globalThis.fetch = mockFetch;
    const conversationId = "11111111-1111-4111-8111-111111111111";
    const clientMessageId = "22222222-2222-4222-8222-222222222222";
    const request = new Request(
      `https://agentarts-personal-assistant.pages.dev/api/conversations/${conversationId}/invocations/${clientMessageId}/cancel`,
      {
        method: "POST",
      },
    );

    const response = await onRequestPostCancellation({
      request,
      env,
      params: {
        conversation_id: conversationId,
        client_message_id: clientMessageId,
      },
    });
    const forwardedRequest = mockFetch.mock.calls[0][0];

    expect(forwardedRequest.method).toBe("POST");
    expect(forwardedRequest.url).toBe(
      `${env.AGENTARTS_INVOCATIONS_URL}/api/conversations/${conversationId}/invocations/${clientMessageId}/cancel`,
    );
    expect(response.status).toBe(204);
  });

  it("uses the same Service cancellation path in local Pages mode", async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    globalThis.fetch = mockFetch;
    const conversationId = "11111111-1111-4111-8111-111111111111";
    const clientMessageId = "22222222-2222-4222-8222-222222222222";
    const path = `/api/conversations/${conversationId}/invocations/${clientMessageId}/cancel`;
    const request = new Request(`http://localhost:5173${path}`, {
      method: "POST",
    });

    await onRequestPostCancellation({
      request,
      env: {
        PA_ENV: "local",
        AGENTARTS_INVOCATIONS_URL: "http://localhost:8080",
      },
      params: {
        conversation_id: conversationId,
        client_message_id: clientMessageId,
      },
    });

    expect(mockFetch.mock.calls[0][0].url).toBe(
      `http://localhost:8080${path}`,
    );
  });

  it("returns 502 when the Gateway request fails", async () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(runtimeSessionId);
    globalThis.fetch = vi.fn().mockRejectedValue(new Error("network error"));

    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/invocations",
      {
        method: "POST",
        body: "{}",
      },
    );

    const response = await onRequestPostRoot({ request, env });

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      message: "AgentArts Gateway is unavailable",
    });
    expect(response.headers.get("Set-Cookie")).toContain(
      `pa_runtime_session=${runtimeSessionId}`,
    );
  });

  it("fails clearly when the upstream URL is not configured", async () => {
    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/invocations",
      {
        method: "POST",
        body: "{}",
      },
    );

    const response = await onRequestPostRoot({ request, env: {} });

    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({
      message: "Frontend proxy is not configured",
    });
  });

  it("builds the BFF callback upstream URL from the public callback path", () => {
    expect(
      buildCallbackUpstreamUrl(
        env,
        "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar?state=signed-state&session_uri=urn:test",
      ).toString(),
    ).toBe(
      "https://runtime.example.com/runtimes/personal-assistant/invocations/auth/oauth2/callback/m365-calendar?state=signed-state&session_uri=urn%3Atest",
    );
  });

  it("prefers a direct service callback URL when configured", () => {
    expect(
      buildCallbackUpstreamUrl(
        {
          ...env,
          AGENTARTS_OAUTH_CALLBACK_URL:
            "https://service.example.com/auth/oauth2/callback/m365-calendar",
        },
        "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar?state=signed-state&session_uri=urn:test",
      ).toString(),
    ).toBe(
      "https://service.example.com/auth/oauth2/callback/m365-calendar?state=signed-state&session_uri=urn%3Atest",
    );
  });

  it("BFF callback uses callback auth cookie without forwarding browser auth", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response("<html>done</html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );
    globalThis.fetch = mockFetch;

    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar?state=signed-state&session_uri=urn:test",
      {
        method: "GET",
        headers: {
          Authorization: "Bearer browser-token",
          Cookie:
            "session=browser-cookie; "
            + "pa_oauth2_callback_auth=Bearer%20callback-token; "
            + "pa_oauth2_callback_session=callback-session; "
            + "pa_oauth2_callback_user=callback-user",
        },
      },
    );

    const response = await onRequestGetCalendarCallback({
      request,
      env: {
        ...env,
        OAUTH2_CALLBACK_BFF_SECRET: "bff-secret",
      },
    });
    const forwardedRequest = mockFetch.mock.calls[0][0];

    expect(forwardedRequest.url).toBe(
      "https://runtime.example.com/runtimes/personal-assistant/invocations/auth/oauth2/callback/m365-calendar?state=signed-state&session_uri=urn%3Atest",
    );
    expect(forwardedRequest.headers.get("Accept")).toBe("text/html");
    expect(forwardedRequest.headers.get("Authorization")).toBe(
      "Bearer callback-token",
    );
    expect(forwardedRequest.headers.get("x-hw-agentarts-session-id")).toBe(
      "callback-session",
    );
    expect(forwardedRequest.headers.get("X-HW-AgentGateway-User-Id")).toBe(
      null,
    );
    expect(forwardedRequest.headers.get("Cookie")).toBeNull();
    expect(forwardedRequest.headers.get("x-pa-oauth2-callback-secret")).toBe(
      "bff-secret",
    );
    expect(response.headers.get("Content-Type")).toContain("text/html");
    expect(response.headers.get("Set-Cookie")).toContain(
      "pa_oauth2_callback_auth=; Max-Age=0",
    );
    expect(response.headers.get("Set-Cookie")).toContain(
      "pa_oauth2_callback_session=; Max-Age=0",
    );
    expect(response.headers.get("Set-Cookie")).toContain(
      "pa_oauth2_callback_user=; Max-Age=0",
    );
    expect(await response.text()).toBe("<html>done</html>");
  });

  it("BFF callback does not forward browser callback Authorization", async () => {
    const mockFetch = vi.fn().mockResolvedValue(new Response("<html>done</html>"));
    globalThis.fetch = mockFetch;

    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar?state=signed-state&session_uri=urn:test",
      {
        method: "GET",
        headers: {
          Authorization: "Bearer browser-token",
        },
      },
    );

    await onRequestGetCalendarCallback({
      request,
      env,
    });
    const forwardedRequest = mockFetch.mock.calls[0][0];

    expect(forwardedRequest.headers.get("Authorization")).toBeNull();
  });

  it("BFF callback returns a broadcasting failure page when upstream fails", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error("network error"));

    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar?state=signed-state&session_uri=urn:test",
      {
        method: "GET",
        headers: {
          Cookie:
            "pa_oauth2_callback_auth=Bearer%20callback-token; "
            + "pa_oauth2_callback_session=callback-session; "
            + "pa_oauth2_callback_user=callback-user",
        },
      },
    );

    const response = await onRequestGetCalendarCallback({ request, env });
    const text = await response.text();

    expect(response.status).toBe(502);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(response.headers.get("Set-Cookie")).toContain(
      "pa_oauth2_callback_auth=; Max-Age=0",
    );
    expect(text).toContain("授权失败");
    expect(text).toContain('"request_id":"signed-state"');
    expect(text).toContain('"status":"failed"');
    expect(text).toContain('BroadcastChannel("m365-calendar-auth")');
  });

  it("BFF callback ignores malformed unrelated cookies on failure", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error("network error"));
    const request = new Request(
      "https://agentarts-personal-assistant.pages.dev/auth/callback/m365-calendar?state=signed-state",
      {
        headers: {
          Cookie:
            "unrelated=%; pa_oauth2_callback_auth=Bearer%20callback-token; "
            + "pa_oauth2_callback_session=callback-session",
        },
      },
    );

    const response = await onRequestGetCalendarCallback({ request, env });

    expect(response.status).toBe(502);
    expect(await response.text()).toContain("授权失败");
    expect(response.headers.get("Set-Cookie")).toContain(
      "pa_oauth2_callback_auth=; Max-Age=0",
    );
  });
});
