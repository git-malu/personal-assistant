import { authenticateRequest, errorResponse } from "../../_shared/auth.js";
import { stopRuntimeSession } from "../../_shared/runtime-session.js";
import { withStore } from "../../_shared/store.js";

export async function onRequestDelete({ request, env }) {
  try {
    const userId = await authenticateRequest(request, env);
    const result = await withStore(env, (store) =>
      stopRuntimeSession(request, env, store, userId),
    );
    return Response.json(result);
  } catch (error) {
    return errorResponse(error);
  }
}
