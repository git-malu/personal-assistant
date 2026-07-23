import { proxyInvocationsRequest } from "../../_shared/agentarts-proxy.js";

function route(conversationId) {
  const path = `/api/conversations/${encodeURIComponent(conversationId)}`;
  return { publicPrefix: path, upstreamPrefix: path };
}

function proxy(request, env, conversationId, method) {
  return proxyInvocationsRequest({
    request,
    env,
    ...route(conversationId),
    allowedMethods: [method],
  });
}

export async function onRequestGet({ request, env, params }) {
  return proxy(request, env, params.conversation_id, "GET");
}

export async function onRequestPatch({ request, env, params }) {
  return proxy(request, env, params.conversation_id, "PATCH");
}

export async function onRequestDelete({ request, env, params }) {
  return proxy(request, env, params.conversation_id, "DELETE");
}
