import { authenticateRequest, errorResponse } from "../../../_shared/auth.js";
import { withStore } from "../../../_shared/store.js";

export async function onRequestGet({ request, env, params }) {
  try {
    const userId = await authenticateRequest(request, env);
    const url = new URL(request.url);
    const result = await withStore(env, (store) =>
      store.listMessages(userId, params.id, {
        before: url.searchParams.get("before") || undefined,
        limit: Math.min(Number(url.searchParams.get("limit") || 50), 100),
      }),
    );
    return Response.json(result, {
      headers: { "cache-control": "no-store" },
    });
  } catch (error) {
    return errorResponse(error);
  }
}
