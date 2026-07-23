import { afterEach, describe, expect, it, vi } from "vitest";

import {
  RUNTIME_SESSION_HEADER,
  applyRuntimeSessionCookie,
  buildExpiredRuntimeSessionCookie,
  resolveRuntimeSession,
} from "./runtime-session.js";

describe("Runtime Session Cookie resolver", () => {
  const runtimeSessionId = "123e4567-e89b-42d3-a456-426614174000";

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reuses only an exact valid UUID v4 cookie", () => {
    const request = new Request("https://example.com/api/conversations", {
      headers: {
        Cookie: `other_pa_runtime_session=bad; pa_runtime_session=${runtimeSessionId}`,
      },
    });

    expect(resolveRuntimeSession(request, {})).toEqual({
      id: runtimeSessionId,
      setCookie: null,
    });
  });

  it.each([null, "not-a-uuid", "123e4567-e89b-12d3-a456-426614174000"])(
    "generates a secure HttpOnly cookie for missing or invalid value %s",
    (value) => {
      vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(runtimeSessionId);
      const headers = value
        ? { Cookie: `pa_runtime_session=${value}` }
        : undefined;
      const request = new Request("https://example.com/invocations", { headers });

      const resolution = resolveRuntimeSession(request, {});
      const responseHeaders = new Headers();
      applyRuntimeSessionCookie(responseHeaders, resolution);

      expect(resolution.id).toBe(runtimeSessionId);
      expect(responseHeaders.get("Set-Cookie")).toBe(
        `pa_runtime_session=${runtimeSessionId}; Path=/; HttpOnly; SameSite=Lax; Secure`,
      );
    },
  );

  it("omits Secure only for explicit local preview", () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(runtimeSessionId);
    const resolution = resolveRuntimeSession(
      new Request("http://localhost/invocations"),
      { PA_ENV: "local" },
    );

    expect(resolution.setCookie).not.toContain("Secure");
    expect(buildExpiredRuntimeSessionCookie({ PA_ENV: "local" })).toBe(
      "pa_runtime_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax",
    );
  });

  it("exports the sole upstream routing header name", () => {
    expect(RUNTIME_SESSION_HEADER).toBe("x-hw-agentarts-session-id");
  });
});
