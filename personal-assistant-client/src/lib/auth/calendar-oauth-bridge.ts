export const CALENDAR_OAUTH_PROVIDER = "m365-calendar-provider";

export const CALENDAR_OAUTH_CHANNEL_NAME = "m365-calendar-auth";

export const CALENDAR_OAUTH_PENDING_MESSAGE = "正在完成日历授权，请稍候…";

export const CALENDAR_OAUTH_FAILED_MESSAGE = "日历授权完成失败，请重新发起授权。";

export interface CalendarOAuthResponse {
  type: "m365-calendar-auth";
  requestId: string;
  provider: string;
  status: "complete" | "failed" | "pending";
  message: string;
  state?: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

export function openCalendarOAuthChannel(): BroadcastChannel | null {
  if (
    typeof window === "undefined" ||
    typeof BroadcastChannel === "undefined"
  ) {
    return null;
  }

  try {
    return new BroadcastChannel(CALENDAR_OAUTH_CHANNEL_NAME);
  } catch {
    return null;
  }
}

export function isCalendarOAuthResponse(
  value: unknown,
): value is CalendarOAuthResponse {
  if (!isRecord(value) || value.type !== "m365-calendar-auth") {
    return false;
  }

  return (
    isString(value.requestId) &&
    isString(value.provider) &&
    (value.status === "complete" ||
      value.status === "failed" ||
      value.status === "pending") &&
    isString(value.message) &&
    (value.state === undefined || value.state === null || isString(value.state))
  );
}
