export const RUNTIME_SESSION_COOKIE = "pa_runtime_session";
export const RUNTIME_SESSION_HEADER = "x-hw-agentarts-session-id";
export const RUNTIME_SESSION_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function parseCookies(request) {
  const header = request.headers.get("Cookie");
  if (!header) return {};

  const cookies = {};
  for (const part of header.split(";")) {
    const [rawName, ...rawValue] = part.trim().split("=");
    if (!rawName) continue;
    try {
      cookies[rawName] = decodeURIComponent(rawValue.join("="));
    } catch {
      cookies[rawName] = "";
    }
  }
  return cookies;
}

function runtimeCookie(value, env, { expired = false } = {}) {
  const attributes = [
    `${RUNTIME_SESSION_COOKIE}=${expired ? "" : value}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
  ];
  if (expired) attributes.splice(1, 0, "Max-Age=0");
  if (env?.PA_ENV !== "local") attributes.push("Secure");
  return attributes.join("; ");
}

export function resolveRuntimeSession(request, env) {
  const value = parseCookies(request)[RUNTIME_SESSION_COOKIE];
  if (value && RUNTIME_SESSION_PATTERN.test(value)) {
    return { id: value, setCookie: null };
  }

  const id = crypto.randomUUID();
  return { id, setCookie: runtimeCookie(id, env) };
}

export function applyRuntimeSessionCookie(headers, resolution) {
  if (resolution.setCookie) {
    headers.append("Set-Cookie", resolution.setCookie);
  }
}

export function buildExpiredRuntimeSessionCookie(env) {
  return runtimeCookie("", env, { expired: true });
}
