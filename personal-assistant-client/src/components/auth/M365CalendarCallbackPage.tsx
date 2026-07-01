import {
  CALENDAR_OAUTH_FAILED_MESSAGE,
  CALENDAR_OAUTH_PENDING_MESSAGE,
  CALENDAR_OAUTH_PROVIDER,
  isCalendarOAuthResponse,
  openCalendarOAuthChannel,
  type CalendarOAuthResponse,
} from "@/lib/auth/calendar-oauth-bridge";
import { useEffect, useMemo, useRef, useState } from "react";

type CallbackStatus = "pending" | "complete" | "failed";

export function buildBackendCalendarCallbackUrl(
  origin = window.location.origin,
  search = window.location.search,
): URL {
  const target = new URL(
    "/invocations/auth/oauth2/callback/m365-calendar",
    origin,
  );
  target.search = search;
  return target;
}

export function getCalendarCallbackState(
  search = window.location.search,
): string | null {
  const params = new URLSearchParams(search);
  return params.get("state") || params.get("custom_state") || null;
}

function broadcastCalendarOAuthStatus(response: CalendarOAuthResponse) {
  try {
    const channel = openCalendarOAuthChannel();
    channel?.postMessage(response);
    window.setTimeout(() => channel?.close(), 1000);
  } catch {}
  try {
    window.opener?.postMessage(response, window.location.origin);
  } catch {}
}

export default function M365CalendarCallbackPage() {
  const params = useMemo(
    () => new URLSearchParams(window.location.search),
    [],
  );
  const startedRef = useRef(false);
  const [status, setStatus] = useState<CallbackStatus>("pending");
  const [message, setMessage] = useState(CALENDAR_OAUTH_PENDING_MESSAGE);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    let cancelled = false;
    async function completeViaLocalProxyFallback() {
      const callbackState = getCalendarCallbackState();
      try {
        const response = await fetch(
          buildBackendCalendarCallbackUrl(window.location.origin, window.location.search),
          { headers: { Accept: "application/json" } },
        );
        if (!response.ok) {
          throw new Error(`OAuth2 callback failed: ${response.status}`);
        }
        const data = (await response.json()) as unknown;
        if (!isCalendarOAuthResponse(data)) {
          throw new Error("Invalid OAuth2 callback response");
        }
        if (cancelled) return;
        if (data.status === "pending") {
          setStatus("pending");
          setMessage(data.message);
          return;
        }

        setStatus(data.status);
        setMessage(data.message);
        broadcastCalendarOAuthStatus(data);
        if (data.status === "complete") {
          window.setTimeout(() => window.close(), 1200);
        }
      } catch {
        if (cancelled) return;
        const errorMessage = params.get("error_description") || CALENDAR_OAUTH_FAILED_MESSAGE;
        setStatus("failed");
        setMessage(errorMessage);
        broadcastCalendarOAuthStatus({
          type: "m365-calendar-auth",
          requestId: callbackState ?? "",
          provider: CALENDAR_OAUTH_PROVIDER,
          status: "failed",
          message: errorMessage,
          state: callbackState,
        });
      }
    }

    void completeViaLocalProxyFallback();
    return () => {
      cancelled = true;
    };
  }, [params]);

  const isComplete = status === "complete";
  const isFailed = status === "failed";

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-6">
      <section className="w-full max-w-md rounded-2xl border bg-card p-6 text-center shadow-sm">
        <div
          className={
            isComplete
              ? "mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-green-100 text-green-700"
              : isFailed
                ? "mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-red-100 text-red-700"
                : "mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-blue-100 text-blue-700"
          }
        >
          {isComplete ? "✓" : isFailed ? "!" : "..."}
        </div>
        <h1 className="text-lg font-semibold">
          {isComplete ? "授权完成" : isFailed ? "授权失败" : "正在授权"}
        </h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">{message}</p>
        <button
          type="button"
          onClick={() => window.close()}
          className="mt-6 inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          关闭窗口
        </button>
      </section>
    </main>
  );
}
