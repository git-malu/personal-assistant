import { authenticateRequest, errorResponse } from "../../_shared/auth.js";
import { ensureRuntimeSession } from "../../_shared/runtime-session.js";
import { withStore } from "../../_shared/store.js";

export async function onRequestPost({ request, env }) {
  try {
    const userId = await authenticateRequest(request, env);
    const result = await withStore(env, (store) =>
      ensureRuntimeSession(request, env, store, userId),
    );
    return Response.json(result, {
      headers: { "cache-control": "no-store" },
    });
  } catch (error) {
    return errorResponse(error);
  }
}
