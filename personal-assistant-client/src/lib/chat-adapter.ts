import type {
  ChatModelAdapter,
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import { handleChatEvent } from "@/lib/chat/chat-event-handler";
import { invokeChat } from "@/lib/chat/chat-api-client";
import { parseSSEStream } from "@/lib/chat/sse-parser";
import { getSessionId } from "@/lib/chat/session";
export { getSessionId, resetSessionId } from "@/lib/chat/session";

/**
 * ChatModelAdapter that connects to the backend SSE API.
 *
 * Requests use `/invocations` in every environment. The Vite dev proxy
 * forwards them to the local service, while the production Cloudflare Pages
 * Function forwards them to AgentArts Runtime.
 */
export function createChatAdapter(
  getConversationId: () => string | undefined,
): ChatModelAdapter {
  return {
  async *run(options: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult, void> {
    const { messages, abortSignal } = options;
    const lastUserMessage = [...messages]
      .reverse()
      .find((m) => m.role === "user");
    const query: string =
      lastUserMessage?.content.find((p) => p.type === "text")?.text ?? "";
    const assistantMessageId =
      options.unstable_assistantMessageId ?? "unknown";
    let fullText = "";

    const conversationId = getConversationId();
    if (!conversationId) {
      throw new Error("Conversation is still initializing. Please try again.");
    }
    const clientMessageId = lastUserMessage?.id ?? crypto.randomUUID();
    const stream = await invokeChat(
      query,
      abortSignal,
      conversationId,
      clientMessageId,
    );

    for await (const event of parseSSEStream(stream)) {
      const result = handleChatEvent(event, {
        assistantMessageId,
        fullText,
      });
      fullText = result.fullText;

      for (const text of result.contentUpdates) {
        yield {
          content: [{ type: "text", text }],
        };
      }

      if (result.done) break;
    }

    yield {
      content: [{ type: "text", text: fullText }],
      status: { type: "complete", reason: "stop" },
    };
    },
  };
}

export const chatAdapter = createChatAdapter(() => getSessionId());
