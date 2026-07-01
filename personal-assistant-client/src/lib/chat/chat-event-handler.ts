import { useAuthCardStore } from "@/stores/auth-card-store";
import type { SSEEvent } from "@/types/chat";

interface ChatEventContext {
  assistantMessageId: string;
  fullText: string;
}

interface ChatEventResult {
  fullText: string;
  contentUpdates: string[];
  done: boolean;
}

export function handleChatEvent(
  event: SSEEvent,
  context: ChatEventContext,
): ChatEventResult {
  if (event.error) {
    throw new Error(event.error);
  }

  let fullText = context.fullText;
  const contentUpdates: string[] = [];

  if (typeof event.token === "string") {
    fullText += event.token;
    contentUpdates.push(fullText);
  }

  const systemMessage =
    typeof event.system_message === "string" ? event.system_message : "";
  const isAuthEvent =
    event.auth_required === true ||
    event.auth_complete === true ||
    event.auth_failed === true;

  if (
    event.auth_required &&
    event.auth_url &&
    event.provider &&
    systemMessage.trim()
  ) {
    useAuthCardStore.getState().setAuth(
      context.assistantMessageId,
      event.provider,
      event.auth_url,
      systemMessage,
      event.oauth2_state,
    );
  }

  if (event.auth_complete && event.provider) {
    useAuthCardStore
      .getState()
      .setAuthComplete(
        event.provider,
        systemMessage || undefined,
        event.oauth2_state,
      );
  }

  if (event.auth_failed && event.provider) {
    useAuthCardStore
      .getState()
      .setAuthFailed(
        event.provider,
        systemMessage || undefined,
        event.oauth2_state,
      );
  }

  if (!isAuthEvent && systemMessage.trim()) {
    fullText += systemMessage;
    contentUpdates.push(fullText);
  }

  return {
    fullText,
    contentUpdates,
    done: event.done === true,
  };
}
