import { afterEach, describe, expect, it, vi } from "vitest";

import { onRequestPost as onRequestPostRoot } from "./invocations.js";
import {
  buildCallbackUpstreamUrl,
  onRequestGet as onRequestGetCalendarCallback,
} from "./auth/callback/m365-calendar.js";

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
          "X-HW-AgentGateway-User-Id": "test-user",
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
      "test-session",
    );
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
      "pa_oauth2_callback_session=test-session",
    );
    expect(response.headers.get("Set-Cookie")).toContain(
      "pa_oauth2_callback_user=test-user",
    );
    expect(response.headers.get("Set-Cookie")).toContain(
      "Path=/auth/callback/m365-calendar",
    );
    expect(response.headers.get("Set-Cookie")).toContain("HttpOnly");
    expect(response.headers.get("Set-Cookie")).toContain("SameSite=Lax");
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

    const response = await onRequestPostRoot({ request, env });

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
      "https://runtime.example.com/runtimes/personal-assistant/invocations/auth/oauth2/callback/m365-calendar?state=signed-state&session_uri=urn:test",
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
      "https://service.example.com/auth/oauth2/callback/m365-calendar?state=signed-state&session_uri=urn:test",
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
      "https://runtime.example.com/runtimes/personal-assistant/invocations/auth/oauth2/callback/m365-calendar?state=signed-state&session_uri=urn:test",
    );
    expect(forwardedRequest.headers.get("Accept")).toBe("text/html");
    expect(forwardedRequest.headers.get("Authorization")).toBe(
      "Bearer callback-token",
    );
    expect(forwardedRequest.headers.get("x-hw-agentarts-session-id")).toBe(
      "callback-session",
    );
    expect(forwardedRequest.headers.get("X-HW-AgentGateway-User-Id")).toBe(
      "callback-user",
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
});
