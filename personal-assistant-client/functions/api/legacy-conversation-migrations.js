import { authenticateRequest, errorResponse } from "../_shared/auth.js";
import { withStore } from "../_shared/store.js";

function migrationUrl(env) {
  const url = new URL(env.AGENTARTS_INVOCATIONS_URL);
  url.pathname = url.pathname.replace(
    /\/invocations\/?$/,
    "/invocations/internal/legacy-conversation-migrations",
  );
  return url;
}

export async function onRequestPost({ request, env }) {
  try {
    const userId = await authenticateRequest(request, env);
    const lease = await withStore(env, (store) => store.getActiveLease(userId));
    const headers = new Headers({
      "content-type": "application/json",
      "x-hw-agentgateway-user-id": userId,
      "x-hw-agentarts-session-id":
        lease?.runtime_session_id || crypto.randomUUID(),
    });
    const authorization = request.headers.get("authorization");
    if (authorization) headers.set("authorization", authorization);
    const response = await fetch(migrationUrl(env), {
      method: "POST",
      headers,
      body: await request.text(),
    });
    return new Response(response.body, {
      status: response.status,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  } catch (error) {
    return errorResponse(error);
  }
}
