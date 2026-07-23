import { proxyInvocationsRequest } from "../../../_shared/agentarts-proxy.js";

export async function onRequestGet({ request, env, params }) {
  const path = `/api/conversations/${encodeURIComponent(params.conversation_id)}/messages`;
  return proxyInvocationsRequest({
    request,
    env,
    publicPrefix: path,
    upstreamPrefix: path,
    allowedMethods: ["GET"],
    allowedQueryParameters: ["cursor", "limit"],
  });
}
