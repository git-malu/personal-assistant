function runtimeUrl(env, action) {
  const invocations = new URL(env.AGENTARTS_INVOCATIONS_URL);
  invocations.pathname = invocations.pathname.replace(
    /\/invocations\/?$/,
    `/${action}`,
  );
  return invocations;
}

function authHeaders(request) {
  const headers = new Headers();
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);
  return headers;
}

export async function ensureRuntimeSession(request, env, store, userId) {
  const existing = await store.getActiveLease(userId);
  if (existing?.status === "active") {
    return { status: "ready", session_id: existing.runtime_session_id };
  }
  if (existing?.status === "starting") {
    return { status: "warming" };
  }

  const ownerToken = crypto.randomUUID();
  const lease = await store.createStartingLease(userId, ownerToken);
  if (!lease) return { status: "warming" };

  const started = Date.now();
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    Number(env.RUNTIME_PREWARM_TIMEOUT_MS || 2500),
  );
  try {
    const response = await fetch(runtimeUrl(env, "sessions-start"), {
      method: "POST",
      headers: authHeaders(request),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`sessions-start returned ${response.status}`);
    const payload = await response.json();
    const sessionId = payload?.data?.session_id;
    if (!sessionId) throw new Error("sessions-start response omitted session_id");
    await store.activateLease(lease.id, sessionId, Date.now() - started);
    return { status: "ready", session_id: sessionId };
  } catch (error) {
    await store.degradeLease(lease.id, error);
    return { status: "degraded" };
  } finally {
    clearTimeout(timeout);
  }
}

export async function stopRuntimeSession(request, env, store, userId) {
  const lease = await store.stopLease(userId);
  if (!lease?.runtime_session_id) return { status: "stopped" };
  try {
    const headers = authHeaders(request);
    headers.set("x-hw-agentarts-session-id", lease.runtime_session_id);
    const response = await fetch(runtimeUrl(env, "sessions-stop"), {
      method: "POST",
      headers,
    });
    if (!response.ok) throw new Error(`sessions-stop returned ${response.status}`);
    await store.finishStop(lease.id, true);
    return { status: "stopped" };
  } catch (error) {
    await store.finishStop(lease.id, false, error);
    return { status: "degraded" };
  }
}
