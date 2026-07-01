function mapConversation(row) {
  return {
    id: row.id,
    title: row.title,
    status: row.status,
    version: row.version,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

export async function withStore(env, callback) {
  if (env?.CONVERSATION_STORE) {
    return callback(env.CONVERSATION_STORE);
  }
  if (!env?.HYPERDRIVE?.connectionString) {
    throw new Error("HYPERDRIVE binding is not configured");
  }

  const { Client } = await import("pg");
  const client = new Client({
    connectionString: env.HYPERDRIVE.connectionString,
    application_name: "personal-assistant-bff",
  });
  await client.connect();
  const store = createPostgresStore(client);
  try {
    return await callback(store);
  } finally {
    await client.end();
  }
}

export function createPostgresStore(client) {
  return {
    async listConversations(userId, { after, limit = 30, status = "regular" }) {
      const values = [userId, limit + 1];
      const statusFilter =
        status === "all"
          ? "status <> 'deleted'"
          : "status = $3";
      if (status !== "all") values.push(status);
      let cursor = "";
      if (after) {
        const [updatedAt, id] = atob(after).split("|");
        values.push(updatedAt, id);
        const offset = status === "all" ? 3 : 4;
        cursor = `AND (updated_at, id) < ($${offset}::timestamptz, $${offset + 1}::uuid)`;
      }
      const { rows } = await client.query(
        `SELECT id, title, status, version, created_at, updated_at
           FROM conversations
          WHERE user_id = $1 AND ${statusFilter} ${cursor}
          ORDER BY updated_at DESC, id DESC
          LIMIT $2`,
        values,
      );
      const hasMore = rows.length > limit;
      const page = rows.slice(0, limit);
      const last = page.at(-1);
      return {
        conversations: page.map(mapConversation),
        next_cursor:
          hasMore && last
            ? btoa(`${new Date(last.updated_at).toISOString()}|${last.id}`)
            : undefined,
      };
    },

    async createConversation(userId, { id, title, idempotencyKey }) {
      const { rows } = await client.query(
        `INSERT INTO conversations (id, user_id, title, idempotency_key)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (user_id, idempotency_key)
           WHERE idempotency_key IS NOT NULL
         DO UPDATE SET updated_at = conversations.updated_at
         RETURNING id, title, status, version, created_at, updated_at`,
        [id, userId, title || "新对话", idempotencyKey || null],
      );
      return mapConversation(rows[0]);
    },

    async getConversation(userId, id) {
      const { rows } = await client.query(
        `SELECT id, title, status, version, created_at, updated_at
           FROM conversations
          WHERE user_id = $1 AND id = $2 AND status <> 'deleted'`,
        [userId, id],
      );
      return rows[0] ? mapConversation(rows[0]) : null;
    },

    async updateConversation(userId, id, patch) {
      const { rows } = await client.query(
        `UPDATE conversations
            SET title = COALESCE($3, title),
                status = COALESCE($4, status),
                version = version + 1,
                updated_at = NOW()
          WHERE user_id = $1 AND id = $2 AND status <> 'deleted'
          RETURNING id, title, status, version, created_at, updated_at`,
        [userId, id, patch.title ?? null, patch.status ?? null],
      );
      return rows[0] ? mapConversation(rows[0]) : null;
    },

    async deleteConversation(userId, id) {
      const result = await client.query(
        `UPDATE conversations
            SET status = 'deleted', deleted_at = NOW(), updated_at = NOW()
          WHERE user_id = $1 AND id = $2 AND status <> 'deleted'`,
        [userId, id],
      );
      return result.rowCount > 0;
    },

    async listMessages(userId, conversationId, { before, limit = 50 }) {
      const values = [userId, conversationId, limit + 1];
      const cursor = before ? "AND m.sequence < $4" : "";
      if (before) values.push(Number(before));
      const { rows } = await client.query(
        `SELECT m.id, m.parent_id, m.role, m.content, m.sequence,
                m.status, m.created_at
           FROM conversation_messages m
           JOIN conversations c ON c.id = m.conversation_id
          WHERE c.user_id = $1 AND c.id = $2 AND c.status <> 'deleted'
                ${cursor}
          ORDER BY m.sequence DESC
          LIMIT $3`,
        values,
      );
      const hasMore = rows.length > limit;
      const page = rows.slice(0, limit).reverse();
      return {
        messages: page,
        next_cursor: hasMore ? String(page[0]?.sequence) : undefined,
      };
    },

    async appendMessage(userId, conversationId, message) {
      const query = () =>
        client.query(
          `WITH target_conversation AS (
             SELECT c.id
               FROM conversations c
              WHERE c.user_id = $1 AND c.id = $2 AND c.status <> 'deleted'
              FOR UPDATE
           )
           INSERT INTO conversation_messages
             (id, conversation_id, parent_id, role, content, sequence, status)
           SELECT $3, c.id,
                  COALESCE(
                    $4,
                    (SELECT id FROM conversation_messages
                      WHERE conversation_id = c.id
                      ORDER BY sequence DESC LIMIT 1)
                  ),
                  $5, $6::jsonb,
                  COALESCE((SELECT MAX(sequence) + 1
                              FROM conversation_messages
                             WHERE conversation_id = c.id), 1),
                  $7
             FROM target_conversation c
           ON CONFLICT (id) DO UPDATE
              SET status = CASE
                    WHEN EXCLUDED.status = 'pending'
                    THEN conversation_messages.status
                    ELSE EXCLUDED.status
                  END,
                  updated_at = NOW()
            WHERE conversation_messages.conversation_id = EXCLUDED.conversation_id
              AND conversation_messages.role = EXCLUDED.role
              AND conversation_messages.content = EXCLUDED.content
           RETURNING id, parent_id, role, content, sequence, status, created_at,
                     (xmax <> 0) AS reused`,
          [
            userId,
            conversationId,
            message.id,
            message.parent_id ?? null,
            message.role,
            JSON.stringify(message.content),
            message.status ?? "complete",
          ],
        );

      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          const { rows } = await query();
          return rows[0] ?? null;
        } catch (error) {
          if (
            error?.code === "23505" &&
            error?.constraint ===
              "conversation_messages_conversation_sequence_uq" &&
            attempt < 2
          ) {
            continue;
          }
          throw error;
        }
      }
      return null;
    },

    async getActiveLease(userId) {
      const { rows } = await client.query(
        `SELECT * FROM runtime_session_leases
          WHERE user_id = $1 AND status IN ('starting', 'active')
          ORDER BY created_at DESC LIMIT 1`,
        [userId],
      );
      return rows[0] ?? null;
    },

    async createStartingLease(userId, ownerToken) {
      const id = crypto.randomUUID();
      try {
        const { rows } = await client.query(
          `INSERT INTO runtime_session_leases
             (id, user_id, status, owner_token)
           VALUES ($1, $2, 'starting', $3)
           RETURNING *`,
          [id, userId, ownerToken],
        );
        return rows[0];
      } catch (error) {
        if (error?.code === "23505") return null;
        throw error;
      }
    },

    async activateLease(id, sessionId, latencyMs, source = "explicit") {
      const { rows } = await client.query(
        `UPDATE runtime_session_leases
            SET runtime_session_id = $2, status = 'active', source = $4,
                started_at = NOW(), last_used_at = NOW(),
                start_latency_ms = $3, updated_at = NOW()
          WHERE id = $1 RETURNING *`,
        [id, sessionId, latencyMs, source],
      );
      return rows[0];
    },

    async recordImplicitLease(userId, sessionId) {
      const ownerToken = crypto.randomUUID();
      const lease = await this.createStartingLease(userId, ownerToken);
      if (!lease) return this.getActiveLease(userId);
      return this.activateLease(lease.id, sessionId, 0, "implicit");
    },

    async degradeLease(id, reason) {
      await client.query(
        `UPDATE runtime_session_leases
            SET status = 'degraded', failure_reason = $2, updated_at = NOW()
          WHERE id = $1`,
        [id, String(reason).slice(0, 500)],
      );
    },

    async stopLease(userId) {
      const { rows } = await client.query(
        `UPDATE runtime_session_leases
            SET status = 'stopping', updated_at = NOW()
          WHERE id = (
            SELECT id FROM runtime_session_leases
             WHERE user_id = $1 AND status = 'active'
             ORDER BY created_at DESC LIMIT 1
          )
          RETURNING *`,
        [userId],
      );
      return rows[0] ?? null;
    },

    async finishStop(id, success, reason) {
      await client.query(
        `UPDATE runtime_session_leases
            SET status = $2, ended_at = CASE WHEN $3 THEN NOW() ELSE ended_at END,
                failure_reason = $4, updated_at = NOW()
          WHERE id = $1`,
        [id, success ? "stopped" : "stop_failed", success, reason ?? null],
      );
    },
  };
}
