import { describe, expect, it, vi } from "vitest";

import { createPostgresStore } from "./store.js";

const message = {
  id: "message-1",
  role: "user",
  content: [{ type: "text", text: "hello" }],
  status: "pending",
};

describe("createPostgresStore", () => {
  it("scopes idempotent message updates to the same conversation and content", async () => {
    const query = vi.fn().mockResolvedValue({
      rows: [{ id: "message-1", status: "pending" }],
    });
    const store = createPostgresStore({ query });

    const result = await store.appendMessage("user-1", "conversation-1", message);
    const [sql, values] = query.mock.calls[0];

    expect(result).toMatchObject({ id: "message-1", status: "pending" });
    expect(sql).toContain("FOR UPDATE");
    expect(sql).toContain("ON CONFLICT (id) DO UPDATE");
    expect(sql).toContain(
      "conversation_messages.conversation_id = EXCLUDED.conversation_id",
    );
    expect(sql).toContain("conversation_messages.role = EXCLUDED.role");
    expect(sql).toContain("conversation_messages.content = EXCLUDED.content");
    expect(sql).toContain("WHEN EXCLUDED.status = 'pending'");
    expect(sql).toContain("(xmax <> 0) AS reused");
    expect(values).toEqual([
      "user-1",
      "conversation-1",
      "message-1",
      null,
      "user",
      JSON.stringify(message.content),
      "pending",
    ]);
  });

  it("returns null when a message id conflict does not match the same message", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [] });
    const store = createPostgresStore({ query });

    await expect(
      store.appendMessage("user-1", "conversation-1", message),
    ).resolves.toBeNull();
  });

  it("reports reused messages without downgrading a completed status", async () => {
    const query = vi.fn().mockResolvedValue({
      rows: [{ id: "message-1", status: "complete", reused: true }],
    });
    const store = createPostgresStore({ query });

    await expect(
      store.appendMessage("user-1", "conversation-1", message),
    ).resolves.toMatchObject({
      id: "message-1",
      status: "complete",
      reused: true,
    });
  });

  it("retries sequence allocation races", async () => {
    const duplicateSequence = Object.assign(new Error("duplicate sequence"), {
      code: "23505",
      constraint: "conversation_messages_conversation_sequence_uq",
    });
    const query = vi
      .fn()
      .mockRejectedValueOnce(duplicateSequence)
      .mockResolvedValueOnce({ rows: [{ id: "message-1" }] });
    const store = createPostgresStore({ query });

    await expect(
      store.appendMessage("user-1", "conversation-1", message),
    ).resolves.toMatchObject({ id: "message-1" });
    expect(query).toHaveBeenCalledTimes(2);
  });

  it("does not retry unrelated unique violations", async () => {
    const primaryKeyConflict = Object.assign(new Error("duplicate id"), {
      code: "23505",
      constraint: "conversation_messages_pkey",
    });
    const query = vi.fn().mockRejectedValue(primaryKeyConflict);
    const store = createPostgresStore({ query });

    await expect(
      store.appendMessage("user-1", "conversation-1", message),
    ).rejects.toThrow("duplicate id");
    expect(query).toHaveBeenCalledTimes(1);
  });
});
