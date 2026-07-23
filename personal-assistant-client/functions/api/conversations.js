import { proxyInvocationsRequest } from "../_shared/agentarts-proxy.js";

const route = {
  publicPrefix: "/api/conversations",
  upstreamPrefix: "api/conversations",
};

export async function onRequestGet({ request, env }) {
  return proxyInvocationsRequest({
    request,
    env,
    ...route,
    allowedMethods: ["GET"],
    allowedQueryParameters: ["status", "cursor", "limit"],
  });
}

export async function onRequestPost({ request, env }) {
  return proxyInvocationsRequest({
    request,
    env,
    ...route,
    allowedMethods: ["POST"],
  });
}
