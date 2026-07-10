import { useAuthCardStore } from "@/stores/auth-card-store";
import {
  CALENDAR_OAUTH_PROVIDER,
  isCalendarOAuthResponse,
  openCalendarOAuthChannel,
} from "@/lib/auth/calendar-oauth-bridge";
import {
  AlertCircleIcon,
  CheckCircleIcon,
  ShieldCheckIcon,
  XIcon,
} from "lucide-react";
import { useEffect, type FC } from "react";

export interface AuthCardProps {
  messageId?: string;
}

export const AuthCard: FC<AuthCardProps> = ({ messageId }) => {
  const authCard = useAuthCardStore((s) =>
    messageId ? s.cardsByMessageId[messageId] : s,
  );
  const clearAuth = useAuthCardStore((s) => s.clearAuth);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      if (!isCalendarOAuthResponse(event.data)) return;
      const data = event.data;
      if (data.provider === CALENDAR_OAUTH_PROVIDER && !data.state) return;
      // Browser tabs are status observers only. The Service owns OAuth
      // completion, which avoids cross-tab races where another tab completes
      // the same AgentArts session with a different active identity.
      if (data.status === "complete") {
        useAuthCardStore
          .getState()
          .setAuthComplete(data.provider, data.message, data.state);
      }
      if (data.status === "failed") {
        useAuthCardStore
          .getState()
          .setAuthFailed(data.provider, data.message, data.state);
      }
    }

    const channel = openCalendarOAuthChannel();
    if (channel) {
      channel.onmessage = (event) => {
        if (!isCalendarOAuthResponse(event.data)) return;
        if (
          event.data.provider === CALENDAR_OAUTH_PROVIDER &&
          !event.data.state
        ) {
          return;
        }
        // State-scoped status prevents stale callbacks from changing the
        // currently visible AuthCard after a user retries authorization.
        if (event.data.status === "complete") {
          useAuthCardStore.getState().setAuthComplete(
            event.data.provider,
            event.data.message,
            event.data.state,
          );
        }
        if (event.data.status === "failed") {
          useAuthCardStore.getState().setAuthFailed(
            event.data.provider,
            event.data.message,
            event.data.state,
          );
        }
      };
    }

    window.addEventListener("message", handleMessage);
    return () => {
      window.removeEventListener("message", handleMessage);
      channel?.close();
    };
  }, []);

  if (!authCard?.authUrl) return null;

  const isComplete = authCard.authComplete;
  const isFailed = authCard.authFailed;
  const cardClass = isComplete
    ? "flex items-start gap-3 rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950"
    : isFailed
      ? "flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-950"
      : "flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950";
  const textClass = isComplete
    ? "flex-1 text-sm leading-relaxed text-green-800 dark:text-green-200"
    : isFailed
      ? "flex-1 text-sm leading-relaxed text-red-800 dark:text-red-200"
      : "flex-1 text-sm leading-relaxed text-blue-800 dark:text-blue-200";
  const closeClass = isComplete
    ? "inline-flex size-8 items-center justify-center rounded-md text-green-500 transition-colors hover:bg-green-100 dark:hover:bg-green-900"
    : isFailed
      ? "inline-flex size-8 items-center justify-center rounded-md text-red-500 transition-colors hover:bg-red-100 dark:hover:bg-red-900"
      : "inline-flex size-8 items-center justify-center rounded-md text-blue-500 transition-colors hover:bg-blue-100 dark:hover:bg-blue-900";

  return (
    <div className="mb-4 mt-4 w-full">
      <div className={cardClass}>
        {isComplete ? (
          <CheckCircleIcon className="mt-0.5 size-5 shrink-0 text-green-600 dark:text-green-400" />
        ) : isFailed ? (
          <AlertCircleIcon className="mt-0.5 size-5 shrink-0 text-red-600 dark:text-red-400" />
        ) : (
          <ShieldCheckIcon className="mt-0.5 size-5 shrink-0 text-blue-600 dark:text-blue-400" />
        )}
        <p className={textClass}>{authCard.message}</p>
        <div className="flex shrink-0 items-center gap-2">
          {isComplete ? (
            <span className="inline-flex h-8 items-center rounded-md bg-green-600 px-3 text-sm font-medium text-white">
              授权完成
            </span>
          ) : isFailed ? (
            <span className="inline-flex h-8 items-center rounded-md bg-red-600 px-3 text-sm font-medium text-white">
              授权失败
            </span>
          ) : (
            <a
              href={authCard.authUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-8 items-center rounded-md bg-blue-600 px-3 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              点击授权
            </a>
          )}
          <button
            type="button"
            onClick={() => clearAuth(messageId)}
            className={closeClass}
            aria-label="关闭"
          >
            <XIcon className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
