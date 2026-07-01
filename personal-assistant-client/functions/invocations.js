const FORWARDED_HEADERS = [
  "accept",
  "authorization",
  "content-type",
  "x-hw-agentarts-session-id",
  "x-hw-agentgateway-user-id",
];

import { authenticateRequest } from "./_shared/auth.js";
import { withStore } from "./_shared/store.js";

function getInvocationsUrl(env) {
  const value = env?.AGENTARTS_INVOCATIONS_URL?.trim();
  if (!value) {
    throw new Error("AGENTARTS_INVOCATIONS_URL is not configured");
  }

  const url = new URL(value);
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error("AGENTARTS_INVOCATIONS_URL must use http or https");
  }
  return url;
}

async function persistAssistantMessage(
  stream,
  env,
  userId,
  conversationId,
  parentId,
) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() ?? "";
      for (const event of events) {
        for (const line of event.split(/\r?\n/)) {
          if (!line.startsWith("data:")) continue;
          try {
            const payload = JSON.parse(line.slice(5).trim());
            if (typeof payload.token === "string") text += payload.token;
          } catch {
            // Ignore non-JSON custom SSE payloads.
          }
        }
      }
    }
    if (text) {
      await withStore(env, (store) =>
        store.appendMessage(userId, conversationId, {
          id: crypto.randomUUID(),
          parent_id: parentId,
          role: "assistant",
          content: [{ type: "text", text }],
          status: "complete",
        }),
      );
    }
  } finally {
    reader.releaseLock();
  }
}

async function updateUserMessageStatus(env, persistence, status) {
  if (!persistence) return;
  try {
    await withStore(env, (store) =>
      store.appendMessage(persistence.userId, persistence.conversationId, {
        id: persistence.userMessageId,
        role: "user",
        content: [{ type: "text", text: persistence.message }],
        status,
      }),
    );
  } catch (error) {
    console.error("Failed to update persisted user message status", error);
  }
}

export async function onRequestPost({ request, env, waitUntil }) {
  let persistence;
  try {
    const invocationsUrl = getInvocationsUrl(env);
    const bodyBuffer = await request.arrayBuffer();
    let invocation;
    try {
      invocation = JSON.parse(new TextDecoder().decode(bodyBuffer));
    } catch {
      invocation = null;
    }

    const headers = new Headers();
    for (const name of FORWARDED_HEADERS) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }

    if (
      invocation?.conversation_id &&
      (env?.HYPERDRIVE || env?.CONVERSATION_STORE)
    ) {
      const userId = await authenticateRequest(request, env);
      persistence = await withStore(env, async (store) => {
        const conversation = await store.getConversation(
          userId,
          invocation.conversation_id,
        );
        if (!conversation) {
          throw new Response(
            JSON.stringify({ message: "Conversation not found" }),
            { status: 404, headers: { "content-type": "application/json" } },
          );
        }
        const lease = await store.getActiveLease(userId);
        const sessionId =
          lease?.runtime_session_id || crypto.randomUUID();
        headers.set("x-hw-agentarts-session-id", sessionId);
        headers.set("x-hw-agentgateway-user-id", userId);
        if (!lease?.runtime_session_id) {
          await store.recordImplicitLease(userId, sessionId);
        }
        const userMessageId =
          invocation.client_message_id || crypto.randomUUID();
        const userMessage = await store.appendMessage(
          userId,
          invocation.conversation_id,
          {
            id: userMessageId,
            role: "user",
            content: [{ type: "text", text: invocation.message }],
            status: "pending",
          },
        );
        if (!userMessage) {
          throw new Response(
            JSON.stringify({ message: "Message id conflict" }),
            { status: 409, headers: { "content-type": "application/json" } },
          );
        }
        if (userMessage.reused) {
          throw new Response(
            JSON.stringify({ message: "Message already submitted" }),
            { status: 409, headers: { "content-type": "application/json" } },
          );
        }
        return {
          userId,
          conversationId: invocation.conversation_id,
          userMessageId,
          message: invocation.message,
        };
      });
    }

    const upstreamRequest = new Request(invocationsUrl, {
      method: request.method,
      headers,
      body: bodyBuffer,
      redirect: "manual",
    });
    const upstreamResponse = await fetch(upstreamRequest);
    const responseHeaders = new Headers(upstreamResponse.headers);

    responseHeaders.set("Cache-Control", "no-store");

    let responseBody = upstreamResponse.body;
    if (persistence) {
      await updateUserMessageStatus(
        env,
        persistence,
        upstreamResponse.ok ? "complete" : "failed",
      );
    }
    if (responseBody && persistence && upstreamResponse.ok) {
      const [browserStream, persistenceStream] = responseBody.tee();
      responseBody = browserStream;
      const task = persistAssistantMessage(
        persistenceStream,
        env,
        persistence.userId,
        persistence.conversationId,
        persistence.userMessageId,
      );
      if (waitUntil) waitUntil(task);
      else await task;
    }

    return new Response(responseBody, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    if (error instanceof Response) return error;
    await updateUserMessageStatus(env, persistence, "failed");
    console.error("AgentArts proxy request failed", error);
    if (
      error instanceof Error &&
      error.message.startsWith("AGENTARTS_INVOCATIONS_URL")
    ) {
      return Response.json(
        { message: "Frontend proxy is not configured" },
        { status: 500 },
      );
    }
    return Response.json(
      { message: "AgentArts Gateway is unavailable" },
      { status: 502 },
    );
  }
}
