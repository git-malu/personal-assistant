import { proxyInvocationsRequest } from "./_shared/agentarts-proxy.js";

export async function onRequestPost({ request, env }) {
  return proxyInvocationsRequest({ request, env });
}
