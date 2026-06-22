import { authenticateRequest, errorResponse } from "../../_shared/auth.js";
import { withStore } from "../../_shared/store.js";

export async function onRequestGet({ request, env, params }) {
  try {
    const userId = await authenticateRequest(request, env);
    const conversation = await withStore(env, (store) =>
      store.getConversation(userId, params.id),
    );
    return conversation
      ? Response.json(conversation)
      : Response.json({ message: "Conversation not found" }, { status: 404 });
  } catch (error) {
    return errorResponse(error);
  }
}

export async function onRequestPatch({ request, env, params }) {
  try {
    const userId = await authenticateRequest(request, env);
    const body = await request.json();
    if (
      body.status !== undefined &&
      !["regular", "archived"].includes(body.status)
    ) {
      return Response.json({ message: "Invalid status" }, { status: 400 });
    }
    const conversation = await withStore(env, (store) =>
      store.updateConversation(userId, params.id, {
        title:
          typeof body.title === "string" && body.title.trim()
            ? body.title.trim().slice(0, 120)
            : undefined,
        status: body.status,
      }),
    );
    return conversation
      ? Response.json(conversation)
      : Response.json({ message: "Conversation not found" }, { status: 404 });
  } catch (error) {
    return errorResponse(error);
  }
}

export async function onRequestDelete({ request, env, params }) {
  try {
    const userId = await authenticateRequest(request, env);
    const deleted = await withStore(env, (store) =>
      store.deleteConversation(userId, params.id),
    );
    return deleted
      ? new Response(null, { status: 204 })
      : Response.json({ message: "Conversation not found" }, { status: 404 });
  } catch (error) {
    return errorResponse(error);
  }
}
