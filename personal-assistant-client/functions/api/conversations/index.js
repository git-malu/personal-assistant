import { authenticateRequest, errorResponse } from "../../_shared/auth.js";
import { withStore } from "../../_shared/store.js";

export async function onRequestGet({ request, env }) {
  try {
    const userId = await authenticateRequest(request, env);
    const url = new URL(request.url);
    const result = await withStore(env, (store) =>
      store.listConversations(userId, {
        after: url.searchParams.get("after") || undefined,
        limit: Math.min(Number(url.searchParams.get("limit") || 30), 100),
        status: url.searchParams.get("status") || "all",
      }),
    );
    return Response.json(result, {
      headers: { "cache-control": "no-store" },
    });
  } catch (error) {
    return errorResponse(error);
  }
}

export async function onRequestPost({ request, env }) {
  try {
    const userId = await authenticateRequest(request, env);
    const body = await request.json().catch(() => ({}));
    const conversation = await withStore(env, (store) =>
      store.createConversation(userId, {
        id: crypto.randomUUID(),
        title: body.title,
        idempotencyKey:
          request.headers.get("idempotency-key") || crypto.randomUUID(),
      }),
    );
    return Response.json(conversation, { status: 201 });
  } catch (error) {
    return errorResponse(error);
  }
}
