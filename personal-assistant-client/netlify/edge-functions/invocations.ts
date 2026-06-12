import type { Context } from "@netlify/edge-functions";

export default async function handler(
  request: Request,
  context: Context
): Promise<Response> {
  if (request.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const targetUrl = Deno.env.get("AGENTARTS_RUNTIME_URL") ??
    "https://defaultgw-ha3wenzqga.cn-southwest-2.huaweicloud-agentarts.com/runtimes/personal-assistant/invocations";

  const headers = new Headers(request.headers);

  // Inject session ID if not present
  if (!headers.has("x-hw-agentarts-session-id")) {
    headers.set("x-hw-agentarts-session-id", crypto.randomUUID());
  }

  // CUSTOM_JWT mode: browser passes Authorization header — passthrough
  // API_KEY fallback: inject dev key when browser doesn't send auth
  if (!headers.has("Authorization")) {
    const fallbackApiKey = Deno.env.get("AGENTARTS_API_KEY") ?? "pa-dev-api-key-2026";
    headers.set("Authorization", `Bearer ${fallbackApiKey}`);
  }

  // Remove host/origin headers that might confuse upstream
  headers.delete("host");

  const proxyRequest = new Request(targetUrl, {
    method: "POST",
    headers,
    body: request.body,
  });

  return fetch(proxyRequest);
}

export const config = { path: "/invocations" };
