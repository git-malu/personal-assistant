import type {
  ChatModelAdapter,
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import { handleChatEvent } from "@/lib/chat/chat-event-handler";
import { ChatApiError, invokeChat } from "@/lib/chat/chat-api-client";
import {
  startInvocationCancellation,
  waitForInvocationCancellation,
} from "@/lib/chat/cancellation-coordinator";
import { parseSSEStream } from "@/lib/chat/sse-parser";

/**
 * ChatModelAdapter that connects to the backend SSE API.
 *
 * Requests use `/invocations` in every environment. The Vite dev proxy
 * forwards them to the local service, while the production Cloudflare Pages
 * Function forwards them to AgentArts Runtime.
 */
type ConversationIdResolver = (
  options: ChatModelRunOptions,
) => string | undefined | Promise<string | undefined>;
type DuplicateMessageHandler = (conversationId: string) => void;
const defaultConversationIdResolver: ConversationIdResolver = (options) =>
  options.unstable_threadId;

async function* runChat(
  options: ChatModelRunOptions,
  resolveConversationId: ConversationIdResolver,
  onDuplicateMessage?: DuplicateMessageHandler,
): AsyncGenerator<ChatModelRunResult, void> {
    const { messages, abortSignal } = options;
    const lastUserMessage = [...messages]
      .reverse()
      .find((m) => m.role === "user");
    const query: string =
      lastUserMessage?.content.find((p) => p.type === "text")?.text ?? "";
    const assistantMessageId =
      options.unstable_assistantMessageId ?? "unknown";
    const conversationId = await resolveConversationId(options);
    if (!conversationId) {
      throw new Error("Conversation initialization did not return an ID.");
    }
    if (!(await waitForInvocationCancellation(conversationId))) return;
    const clientMessageId = crypto.randomUUID();
    let fullText = "";
    let completed = false;
    let invocationStarted = false;
    let cancellationStarted = false;

    const handleAbort = () => {
      if (!invocationStarted || cancellationStarted) return;
      cancellationStarted = true;
      startInvocationCancellation(conversationId, clientMessageId);
    };
    abortSignal.addEventListener("abort", handleAbort, { once: true });

    try {
      invocationStarted = true;
      if (abortSignal.aborted) handleAbort();

      let stream: ReadableStream<Uint8Array>;
      try {
        stream = await invokeChat(
          query,
          conversationId,
          clientMessageId,
          abortSignal,
        );
      } catch (error) {
        if (
          error instanceof ChatApiError &&
          error.code === "duplicate_message"
        ) {
          onDuplicateMessage?.(conversationId);
        }
        throw error;
      }

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

        if (result.done) {
          completed = true;
          break;
        }
      }
    } finally {
      abortSignal.removeEventListener("abort", handleAbort);
    }

    if (!completed) {
      throw new Error("The chat stream ended before a completion event.");
    }

    yield {
      content: [{ type: "text", text: fullText }],
      status: { type: "complete", reason: "stop" },
    };
}

export function createChatAdapter(
  resolveConversationId: ConversationIdResolver = defaultConversationIdResolver,
  onDuplicateMessage?: DuplicateMessageHandler,
): ChatModelAdapter {
  return {
    run(options) {
      return runChat(options, resolveConversationId, onDuplicateMessage);
    },
  };
}

export const chatAdapter = createChatAdapter();
