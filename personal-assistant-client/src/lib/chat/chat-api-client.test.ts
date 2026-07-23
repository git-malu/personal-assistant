import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth-store";
import { cancelChat } from "./chat-api-client";

describe("cancelChat", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    useAuthStore.getState().clearToken();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    globalThis.fetch = originalFetch;
  });

  it("aborts a cancellation request after the bounded timeout", async () => {
    let cancellationSignal: AbortSignal | undefined;
    globalThis.fetch = vi.fn().mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          cancellationSignal = init?.signal ?? undefined;
          cancellationSignal?.addEventListener(
            "abort",
            () => reject(new DOMException("The operation was aborted", "AbortError")),
            { once: true },
          );
        }),
    ) as unknown as typeof fetch;

    const cancellation = cancelChat(
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    );
    const rejection = expect(cancellation).rejects.toMatchObject({
      name: "AbortError",
    });

    await vi.advanceTimersByTimeAsync(15_000);

    await rejection;
    expect(cancellationSignal?.aborted).toBe(true);
  });
});
