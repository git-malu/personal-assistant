import { proxyInvocationsRequest } from "../../../../../_shared/agentarts-proxy.js";

export async function onRequestPost({ request, env, params }) {
  const path = `/api/conversations/${encodeURIComponent(params.conversation_id)}/invocations/${encodeURIComponent(params.client_message_id)}/cancel`;
  return proxyInvocationsRequest({
    request,
    env,
    publicPrefix: path,
    upstreamPrefix: path,
    allowedMethods: ["POST"],
  });
}
