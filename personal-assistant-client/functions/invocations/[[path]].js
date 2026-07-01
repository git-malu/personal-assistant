const FORWARDED_HEADERS = [
  "accept",
  "authorization",
  "content-type",
  "x-hw-agentarts-session-id",
  "x-hw-agentgateway-user-id",
];

import { authenticateRequest } from "../_shared/auth.js";
import { withStore } from "../_shared/store.js";

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

function getInvocationsUrl(env) {
  const value = env?.AGENTARTS_INVOCATIONS_URL?.trim();
  if (!value) {
    throw new Error("AGENTARTS_INVOCATIONS_URL is not configured");
  }

  const url = new URL(value);
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error("AGENTARTS_INVOCATIONS_URL must use http or https");
  }
  return url;
}

async function persistAssistantMessage(
  stream,
  env,
  userId,
  conversationId,
  parentId,
) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() ?? "";
      for (const event of events) {
        for (const line of event.split(/\r?\n/)) {
          if (!line.startsWith("data:")) continue;
          try {
            const payload = JSON.parse(line.slice(5).trim());
            if (typeof payload.token === "string") text += payload.token;
          } catch {
            // Ignore non-JSON custom SSE payloads.
          }
        }
      }
    }
    if (text) {
      await withStore(env, (store) =>
        store.appendMessage(userId, conversationId, {
          id: crypto.randomUUID(),
          parent_id: parentId,
          role: "assistant",
          content: [{ type: "text", text }],
          status: "complete",
        }),
      );
    }
  } finally {
    reader.releaseLock();
  }
}

async function updateUserMessageStatus(env, persistence, status) {
  if (!persistence) return;
  try {
    await withStore(env, (store) =>
      store.appendMessage(persistence.userId, persistence.conversationId, {
        id: persistence.userMessageId,
        role: "user",
        content: [{ type: "text", text: persistence.message }],
        status,
      }),
    );
  } catch (error) {
    console.error("Failed to update persisted user message status", error);
  }
}

function isRootInvocationsPost(request, publicPrefix) {
  if (request.method !== "POST") return false;
  const prefix = publicPrefix || "/invocations";
  return new URL(request.url).pathname === prefix;
}

export function buildUpstreamUrl(
  env,
  requestUrl,
  { publicPrefix = "/invocations", upstreamPrefix = "" } = {},
) {
  const invocationsUrl = getInvocationsUrl(env);
  const incomingUrl = new URL(requestUrl);
  const incomingPath = incomingUrl.pathname;
  if (
    incomingPath !== publicPrefix &&
    !incomingPath.startsWith(`${publicPrefix}/`)
  ) {
    throw new Error("Unsupported invocations proxy path");
  }

  const basePath = invocationsUrl.pathname.replace(/\/$/, "");
  const normalizedUpstreamPrefix = upstreamPrefix
    ? `/${upstreamPrefix.replace(/^\/|\/$/g, "")}`
    : "";
  const suffix = incomingPath.slice(publicPrefix.length);
  invocationsUrl.pathname = `${basePath}${normalizedUpstreamPrefix}${suffix}`;
  invocationsUrl.search = incomingUrl.search;
  return invocationsUrl;
}

export async function proxyInvocationsRequest({
  request,
  env,
  waitUntil,
  publicPrefix,
  upstreamPrefix,
}) {
  let persistence;
  try {
    const upstreamUrl = buildUpstreamUrl(env, request.url, {
      publicPrefix,
      upstreamPrefix,
    });
    const headers = new Headers();
    for (const name of FORWARDED_HEADERS) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }

    const init = {
      method: request.method,
      headers,
      redirect: "manual",
    };
    let bodyBuffer;
    if (request.method !== "GET" && request.method !== "HEAD") {
      bodyBuffer = await request.arrayBuffer();
      init.body = bodyBuffer;
    }

    let invocation;
    if (
      bodyBuffer &&
      isRootInvocationsPost(request, publicPrefix) &&
      (env?.HYPERDRIVE || env?.CONVERSATION_STORE)
    ) {
      try {
        invocation = JSON.parse(new TextDecoder().decode(bodyBuffer));
      } catch {
        invocation = null;
      }
    }

    if (invocation?.conversation_id) {
      const userId = await authenticateRequest(request, env);
      persistence = await withStore(env, async (store) => {
        const conversation = await store.getConversation(
          userId,
          invocation.conversation_id,
        );
        if (!conversation) {
          throw new Response(
            JSON.stringify({ message: "Conversation not found" }),
            { status: 404, headers: { "content-type": "application/json" } },
          );
        }
        const lease = await store.getActiveLease(userId);
        const sessionId = lease?.runtime_session_id || crypto.randomUUID();
        headers.set("x-hw-agentarts-session-id", sessionId);
        headers.set("x-hw-agentgateway-user-id", userId);
        if (!lease?.runtime_session_id) {
          await store.recordImplicitLease(userId, sessionId);
        }
        const userMessageId =
          invocation.client_message_id || crypto.randomUUID();
        const userMessage = await store.appendMessage(
          userId,
          invocation.conversation_id,
          {
            id: userMessageId,
            role: "user",
            content: [{ type: "text", text: invocation.message }],
            status: "pending",
          },
        );
        if (!userMessage) {
          throw new Response(
            JSON.stringify({ message: "Message id conflict" }),
            { status: 409, headers: { "content-type": "application/json" } },
          );
        }
        if (userMessage.reused) {
          throw new Response(
            JSON.stringify({ message: "Message already submitted" }),
            { status: 409, headers: { "content-type": "application/json" } },
          );
        }
        return {
          userId,
          conversationId: invocation.conversation_id,
          userMessageId,
          message: invocation.message,
        };
      });
    }

    const upstreamRequest = new Request(upstreamUrl, init);
    const upstreamResponse = await fetch(upstreamRequest);
    const responseHeaders = new Headers(upstreamResponse.headers);
    applyCallbackContextCookies(responseHeaders, request);

    responseHeaders.set("Cache-Control", "no-store");

    let responseBody = upstreamResponse.body;
    if (persistence) {
      await updateUserMessageStatus(
        env,
        persistence,
        upstreamResponse.ok ? "complete" : "failed",
      );
    }
    if (responseBody && persistence && upstreamResponse.ok) {
      const [browserStream, persistenceStream] = responseBody.tee();
      responseBody = browserStream;
      const task = persistAssistantMessage(
        persistenceStream,
        env,
        persistence.userId,
        persistence.conversationId,
        persistence.userMessageId,
      );
      if (waitUntil) waitUntil(task);
      else await task;
    }

    return new Response(responseBody, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    if (error instanceof Response) return error;
    await updateUserMessageStatus(env, persistence, "failed");
    console.error("AgentArts proxy request failed", error);
    if (
      error instanceof Error &&
      error.message.startsWith("AGENTARTS_INVOCATIONS_URL")
    ) {
      return Response.json(
        { message: "Frontend proxy is not configured" },
        { status: 500 },
      );
    }
    if (
      error instanceof Error &&
      error.message.startsWith("Unsupported invocations proxy path")
    ) {
      return Response.json(
        { message: "Unsupported proxy path" },
        { status: 404 },
      );
    }
    return Response.json(
      { message: "AgentArts Gateway is unavailable" },
      { status: 502 },
    );
  }
}

export async function onRequestPost({ request, env, waitUntil }) {
  return proxyInvocationsRequest({ request, env, waitUntil });
}

export async function onRequestGet({ request, env }) {
  return proxyInvocationsRequest({ request, env });
}
