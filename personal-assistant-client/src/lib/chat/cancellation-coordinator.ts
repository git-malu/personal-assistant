import { create } from "zustand";

import { cancelChat } from "./chat-api-client";

export type InvocationCancellationStatus =
  | "idle"
  | "cancelling"
  | "cancel_failed";

interface CancellationEntry {
  clientMessageId: string;
  status: Exclude<InvocationCancellationStatus, "idle">;
}

interface InvocationCancellationState {
  byConversation: Record<string, CancellationEntry>;
}

type CancellationResult =
  | { ok: true }
  | { ok: false; error: unknown };

interface PendingCancellation {
  clientMessageId: string;
  result: Promise<CancellationResult>;
}

const AUTOMATIC_ATTEMPTS = 2;
const AUTOMATIC_RETRY_DELAY_MS = 250;
const pendingCancellations = new Map<string, PendingCancellation>();

export const useInvocationCancellationStore =
  create<InvocationCancellationState>(() => ({ byConversation: {} }));

function setCancellationEntry(
  conversationId: string,
  entry: CancellationEntry,
): void {
  useInvocationCancellationStore.setState((state) => ({
    byConversation: {
      ...state.byConversation,
      [conversationId]: entry,
    },
  }));
}

function clearCancellationEntry(
  conversationId: string,
  clientMessageId: string,
): void {
  useInvocationCancellationStore.setState((state) => {
    if (
      state.byConversation[conversationId]?.clientMessageId !== clientMessageId
    ) {
      return state;
    }
    const byConversation = { ...state.byConversation };
    delete byConversation[conversationId];
    return { byConversation };
  });
}

function waitForRetryDelay(): Promise<void> {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, AUTOMATIC_RETRY_DELAY_MS);
  });
}

async function cancelWithRetries(
  conversationId: string,
  clientMessageId: string,
  attempts: number,
): Promise<CancellationResult> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await cancelChat(conversationId, clientMessageId);
      return { ok: true };
    } catch (error) {
      lastError = error;
      if (attempt < attempts) {
        await waitForRetryDelay();
      }
    }
  }
  return { ok: false, error: lastError };
}

function beginCancellation(
  conversationId: string,
  clientMessageId: string,
  attempts: number,
): PendingCancellation {
  setCancellationEntry(conversationId, {
    clientMessageId,
    status: "cancelling",
  });

  let pending: PendingCancellation;
  const result = cancelWithRetries(
    conversationId,
    clientMessageId,
    attempts,
  ).then((outcome) => {
    if (pendingCancellations.get(conversationId) !== pending) {
      return outcome;
    }

    pendingCancellations.delete(conversationId);
    if (outcome.ok) {
      clearCancellationEntry(conversationId, clientMessageId);
    } else {
      setCancellationEntry(conversationId, {
        clientMessageId,
        status: "cancel_failed",
      });
      console.error("Failed to cancel Invocation", outcome.error);
    }
    return outcome;
  });
  pending = { clientMessageId, result };
  pendingCancellations.set(conversationId, pending);
  return pending;
}

export function startInvocationCancellation(
  conversationId: string,
  clientMessageId: string,
): void {
  void beginCancellation(
    conversationId,
    clientMessageId,
    AUTOMATIC_ATTEMPTS,
  ).result;
}

export async function waitForInvocationCancellation(
  conversationId: string,
): Promise<boolean> {
  const pending = pendingCancellations.get(conversationId);
  if (pending) {
    return (await pending.result).ok;
  }
  return !useInvocationCancellationStore.getState().byConversation[
    conversationId
  ];
}

export async function retryInvocationCancellation(
  conversationId: string,
): Promise<boolean> {
  const entry =
    useInvocationCancellationStore.getState().byConversation[conversationId];
  if (!entry) return true;

  const pending = pendingCancellations.get(conversationId);
  if (pending) return (await pending.result).ok;

  return (
    await beginCancellation(conversationId, entry.clientMessageId, 1).result
  ).ok;
}

export function resetInvocationCancellations(): void {
  pendingCancellations.clear();
  useInvocationCancellationStore.setState({ byConversation: {} });
}
