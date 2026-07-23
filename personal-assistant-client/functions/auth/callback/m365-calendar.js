import {
  applyCallbackContextHeaders,
  applyExpiredCallbackContextCookies,
  getCallbackContextFromCookies,
} from "../../_shared/callback-context.js";
import { buildUpstreamUrl } from "../../_shared/agentarts-proxy.js";

const CALLBACK_PUBLIC_PATH = "/auth/callback/m365-calendar";
const CALLBACK_UPSTREAM_PREFIX = "auth/oauth2/callback/m365-calendar";
const CALLBACK_SECRET_HEADER = "x-pa-oauth2-callback-secret";
const CALLBACK_QUERY_PARAMETERS = [
  "state",
  "custom_state",
  "session_uri",
  "error",
  "error_description",
];

function copyCallbackQuery(target, requestUrl) {
  const incomingUrl = new URL(requestUrl);
  target.search = "";
  for (const name of CALLBACK_QUERY_PARAMETERS) {
    for (const value of incomingUrl.searchParams.getAll(name)) {
      target.searchParams.append(name, value);
    }
  }
}

function getDirectCallbackUrl(env, requestUrl) {
  const value = env?.AGENTARTS_OAUTH_CALLBACK_URL?.trim();
  if (!value) return null;

  const target = new URL(value);
  if (target.protocol !== "https:" && target.protocol !== "http:") {
    throw new Error("AGENTARTS_OAUTH_CALLBACK_URL must use http or https");
  }

  copyCallbackQuery(target, requestUrl);
  return target;
}

export function buildCallbackUpstreamUrl(env, requestUrl) {
  return (
    getDirectCallbackUrl(env, requestUrl) ??
    buildUpstreamUrl(env, requestUrl, {
      publicPrefix: CALLBACK_PUBLIC_PATH,
      upstreamPrefix: CALLBACK_UPSTREAM_PREFIX,
      allowedQueryParameters: CALLBACK_QUERY_PARAMETERS,
    })
  );
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function bffFailurePage(requestUrl) {
  const incomingUrl = new URL(requestUrl);
  const state =
    incomingUrl.searchParams.get("state") ??
    incomingUrl.searchParams.get("custom_state") ??
    null;
  const payload = {
    type: "m365-calendar-auth",
    request_id: state ?? "",
    provider: "m365-calendar-provider",
    status: "failed",
    message: "日历授权服务暂时不可用，请返回聊天窗口后重新发起授权。",
    state,
  };
  const payloadJson = JSON.stringify(payload).replace(/</g, "\\u003c");

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>授权失败</title>
</head>
<body>
  <main style="font-family: system-ui, sans-serif; margin: 48px auto; max-width: 420px; text-align: center;">
    <h1>授权失败</h1>
    <p>日历授权服务暂时不可用，请返回聊天窗口后重新发起授权。</p>
    ${state ? `<p style="font-size: 12px; color: #6b7280;">Request ID: ${escapeHtml(state)}</p>` : ""}
    <button type="button" onclick="window.close()">关闭窗口</button>
  </main>
  <script>
    const payload = ${payloadJson};
    try {
      window.opener?.postMessage(payload, window.location.origin);
      new BroadcastChannel("m365-calendar-auth").postMessage(payload);
    } catch (_) {}
  </script>
</body>
</html>`;
}

export async function onRequestGet({ request, env }) {
  try {
    const upstreamUrl = buildCallbackUpstreamUrl(env, request.url);
    const headers = new Headers({ Accept: "text/html" });
    applyCallbackContextHeaders(headers, request);
    const secret = env?.OAUTH2_CALLBACK_BFF_SECRET?.trim();
    if (secret) {
      headers.set(CALLBACK_SECRET_HEADER, secret);
    }

    const upstreamResponse = await fetch(
      new Request(upstreamUrl, {
        method: "GET",
        headers,
        redirect: "manual",
      }),
    );
    const responseHeaders = new Headers(upstreamResponse.headers);
    responseHeaders.set("Cache-Control", "no-store");
    const callbackContext = getCallbackContextFromCookies(request);
    if (callbackContext.authorization || callbackContext.sessionId) {
      applyExpiredCallbackContextCookies(responseHeaders);
    }

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("OAuth2 callback BFF request failed", error);
    const responseHeaders = new Headers({
      "Cache-Control": "no-store",
      "Content-Type": "text/html; charset=utf-8",
    });
    const callbackContext = getCallbackContextFromCookies(request);
    if (callbackContext.authorization || callbackContext.sessionId) {
      applyExpiredCallbackContextCookies(responseHeaders);
    }
    return new Response(bffFailurePage(request.url), {
      status: 502,
      headers: responseHeaders,
    });
  }
}
