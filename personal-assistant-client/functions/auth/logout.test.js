import { describe, expect, it } from "vitest";

import { onRequestPost } from "./logout.js";

describe("POST /auth/logout", () => {
  it("expires Runtime and OAuth callback cookies without calling upstream", async () => {
    const response = await onRequestPost({ env: {} });
    const cookies = response.headers.get("Set-Cookie");

    expect(response.status).toBe(204);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(cookies).toContain("pa_runtime_session=; Max-Age=0");
    expect(cookies).toContain("pa_oauth2_callback_auth=; Max-Age=0");
    expect(cookies).toContain("pa_oauth2_callback_session=; Max-Age=0");
    expect(cookies).toContain("pa_oauth2_callback_user=; Max-Age=0");
  });
});
