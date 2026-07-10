const CALLBACK_AUTH_COOKIE = "pa_oauth2_callback_auth";
const CALLBACK_SESSION_COOKIE = "pa_oauth2_callback_session";
const CALLBACK_USER_COOKIE = "pa_oauth2_callback_user";
const CALLBACK_AUTH_COOKIE_MAX_AGE_SECONDS = 600;
const CALLBACK_AUTH_COOKIE_PATH = "/auth/callback/m365-calendar";

function buildCallbackContextCookie(name, value) {
  const trimmed = value?.trim();
  if (!trimmed) return null;

  return [
    `${name}=${encodeURIComponent(trimmed)}`,
    `Max-Age=${CALLBACK_AUTH_COOKIE_MAX_AGE_SECONDS}`,
    `Path=${CALLBACK_AUTH_COOKIE_PATH}`,
    "HttpOnly",
    "Secure",
    "SameSite=Lax",
  ].join("; ");
}

function buildCallbackContextCookies(request) {
  const cookies = [
    buildCallbackContextCookie(
      CALLBACK_AUTH_COOKIE,
      request.headers.get("Authorization"),
    ),
    buildCallbackContextCookie(
      CALLBACK_SESSION_COOKIE,
      request.headers.get("x-hw-agentarts-session-id"),
    ),
    buildCallbackContextCookie(
      CALLBACK_USER_COOKIE,
      request.headers.get("X-HW-AgentGateway-User-Id"),
    ),
  ];
  return cookies.filter(Boolean);
}

function buildExpiredCallbackContextCookie(name) {
  return [
    `${name}=`,
    "Max-Age=0",
    `Path=${CALLBACK_AUTH_COOKIE_PATH}`,
    "HttpOnly",
    "Secure",
    "SameSite=Lax",
  ].join("; ");
}

export function buildExpiredCallbackContextCookies() {
  return [
    buildExpiredCallbackContextCookie(CALLBACK_AUTH_COOKIE),
    buildExpiredCallbackContextCookie(CALLBACK_SESSION_COOKIE),
    buildExpiredCallbackContextCookie(CALLBACK_USER_COOKIE),
  ];
}

export function applyCallbackContextCookies(headers, request) {
  const cookies = buildCallbackContextCookies(request);
  if (!cookies.length) return;

  for (const cookie of cookies) {
    headers.append("Set-Cookie", cookie);
  }
}

export function applyExpiredCallbackContextCookies(headers) {
  for (const cookie of buildExpiredCallbackContextCookies()) {
    headers.append("Set-Cookie", cookie);
  }
}

export function getCallbackContextFromCookies(request) {
  const cookieHeader = request.headers.get("Cookie");
  if (!cookieHeader) {
    return {};
  }

  const cookies = {};
  for (const part of cookieHeader.split(";")) {
    const [rawKey, ...rawValue] = part.trim().split("=");
    if (!rawKey) continue;
    cookies[rawKey] = decodeURIComponent(rawValue.join("="));
  }

  return {
    authorization: cookies[CALLBACK_AUTH_COOKIE],
    sessionId: cookies[CALLBACK_SESSION_COOKIE],
    userId: cookies[CALLBACK_USER_COOKIE],
  };
}

export function applyCallbackContextHeaders(headers, request) {
  const context = getCallbackContextFromCookies(request);
  if (context.authorization) {
    headers.set("Authorization", context.authorization);
  }
  if (context.sessionId) {
    headers.set("x-hw-agentarts-session-id", context.sessionId);
  }
  if (context.userId) {
    headers.set("X-HW-AgentGateway-User-Id", context.userId);
  }
}
