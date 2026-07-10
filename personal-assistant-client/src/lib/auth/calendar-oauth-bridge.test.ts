import { describe, expect, it } from "vitest";

import {
  CALENDAR_OAUTH_PROVIDER,
  isCalendarOAuthResponse,
} from "@/lib/auth/calendar-oauth-bridge";

describe("calendar OAuth status envelopes", () => {
  it("accepts backend callback status envelopes with OAuth state", () => {
    expect(
      isCalendarOAuthResponse({
        type: "m365-calendar-auth",
        provider: CALENDAR_OAUTH_PROVIDER,
        request_id: "signed-state",
        status: "complete",
        message: "done",
        state: "signed-state",
      }),
    ).toBe(true);
  });

  it("accepts backend callback status envelopes without OAuth state", () => {
    expect(
      isCalendarOAuthResponse({
        type: "m365-calendar-auth",
        provider: CALENDAR_OAUTH_PROVIDER,
        request_id: "signed-state",
        status: "pending",
        message: "working",
        state: null,
      }),
    ).toBe(true);
  });

  it("rejects callback status envelopes with missing fields", () => {
    expect(
      isCalendarOAuthResponse({
        type: "m365-calendar-auth",
        provider: CALENDAR_OAUTH_PROVIDER,
        status: "complete",
        message: "done",
      }),
    ).toBe(false);
  });

  it("rejects malformed callback status envelopes", () => {
    expect(
      isCalendarOAuthResponse({
        type: "m365-calendar-auth",
        provider: CALENDAR_OAUTH_PROVIDER,
        request_id: "signed-state",
        status: "unknown",
        message: "done",
      }),
    ).toBe(false);
  });
});
