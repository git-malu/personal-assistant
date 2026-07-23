import { applyCallbackContextCookies } from "./callback-context.js";
import {
  RUNTIME_SESSION_HEADER,
  applyRuntimeSessionCookie,
  resolveRuntimeSession,
} from "./runtime-session.js";

const FORWARDED_HEADERS = [
  "accept",
  "authorization",
  "content-type",
];

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

export function buildUpstreamUrl(
  env,
  requestUrl,
  {
    publicPrefix = "/invocations",
    upstreamPrefix = "",
    allowedQueryParameters = [],
  } = {},
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
  invocationsUrl.search = "";
  for (const name of allowedQueryParameters) {
    for (const value of incomingUrl.searchParams.getAll(name)) {
      invocationsUrl.searchParams.append(name, value);
    }
  }
  return invocationsUrl;
}

function withRuntimeSessionCookie(response, resolution) {
  const headers = new Headers(response.headers);
  applyRuntimeSessionCookie(headers, resolution);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export async function proxyInvocationsRequest({
  request,
  env,
  publicPrefix = "/invocations",
  upstreamPrefix = "",
  allowedMethods = ["POST"],
  allowedQueryParameters = [],
  snapshotOAuthContext = false,
}) {
  const runtimeSession = resolveRuntimeSession(request, env);
  try {
    if (!allowedMethods.includes(request.method)) {
      return withRuntimeSessionCookie(
        Response.json({ message: "Method not allowed" }, { status: 405 }),
        runtimeSession,
      );
    }
    const upstreamUrl = buildUpstreamUrl(env, request.url, {
      publicPrefix,
      upstreamPrefix,
      allowedQueryParameters,
    });
    const headers = new Headers();
    for (const name of FORWARDED_HEADERS) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    headers.set(RUNTIME_SESSION_HEADER, runtimeSession.id);

    const init = {
      method: request.method,
      headers,
      redirect: "manual",
    };
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = await request.arrayBuffer();
    }

    const upstreamRequest = new Request(upstreamUrl, init);
    const upstreamResponse = await fetch(upstreamRequest);
    const responseHeaders = new Headers(upstreamResponse.headers);
    if (snapshotOAuthContext) {
      applyCallbackContextCookies(
        responseHeaders,
        request,
        runtimeSession.id,
      );
    }
    applyRuntimeSessionCookie(responseHeaders, runtimeSession);

    responseHeaders.set("Cache-Control", "no-store");

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("AgentArts proxy request failed", error);
    if (
      error instanceof Error &&
      error.message.startsWith("AGENTARTS_INVOCATIONS_URL")
    ) {
      return withRuntimeSessionCookie(
        Response.json(
          { message: "Frontend proxy is not configured" },
          { status: 500 },
        ),
        runtimeSession,
      );
    }
    if (
      error instanceof Error &&
      error.message.startsWith("Unsupported invocations proxy path")
    ) {
      return withRuntimeSessionCookie(
        Response.json(
          { message: "Unsupported proxy path" },
          { status: 404 },
        ),
        runtimeSession,
      );
    }
    return withRuntimeSessionCookie(
      Response.json(
        { message: "AgentArts Gateway is unavailable" },
        { status: 502 },
      ),
      runtimeSession,
    );
  }
}
