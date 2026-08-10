import {
  type AuthCardEntry,
  useAuthCardStore,
} from "@/stores/auth-card-store";
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

const EMPTY_AUTH_CARDS: AuthCardEntry[] = [];

export const AuthCard: FC<AuthCardProps> = ({ messageId }) => {
  const messageCards = useAuthCardStore((state) =>
    messageId ? state.cardsByMessageId[messageId] : undefined,
  );
  const latestCard = useAuthCardStore((state) => state);
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
      const authMessageId =
        messageId ?? useAuthCardStore.getState().messageId;
      if (!authMessageId) return;
      if (data.status === "complete") {
        useAuthCardStore
          .getState()
          .setAuthComplete(
            authMessageId,
            data.provider,
            data.message,
            data.state,
          );
      }
      if (data.status === "failed") {
        useAuthCardStore
          .getState()
          .setAuthFailed(
            authMessageId,
            data.provider,
            data.message,
            data.state,
          );
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
        const authMessageId =
          messageId ?? useAuthCardStore.getState().messageId;
        if (!authMessageId) return;
        // State-scoped status prevents stale callbacks from changing the
        // currently visible AuthCard after a user retries authorization.
        if (event.data.status === "complete") {
          useAuthCardStore.getState().setAuthComplete(
            authMessageId,
            event.data.provider,
            event.data.message,
            event.data.state,
          );
        }
        if (event.data.status === "failed") {
          useAuthCardStore.getState().setAuthFailed(
            authMessageId,
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
  }, [messageId]);

  const authCards = messageId
    ? (messageCards ?? EMPTY_AUTH_CARDS)
    : latestCard.authUrl
      ? [latestCard]
      : EMPTY_AUTH_CARDS;

  if (!authCards.length) return null;

  return (
    <div
      data-slot="auth-card-list"
      className="my-4 flex w-full flex-col gap-3"
    >
      {authCards.map((authCard) => {
        const isComplete = authCard.authComplete;
        const isFailed = authCard.authFailed;
        const cardClass = isComplete
          ? "flex min-w-0 flex-col gap-3 rounded-lg border border-green-200 bg-green-50 p-4 sm:flex-row sm:items-start dark:border-green-800 dark:bg-green-950"
          : isFailed
            ? "flex min-w-0 flex-col gap-3 rounded-lg border border-red-200 bg-red-50 p-4 sm:flex-row sm:items-start dark:border-red-800 dark:bg-red-950"
            : "flex min-w-0 flex-col gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 sm:flex-row sm:items-start dark:border-blue-800 dark:bg-blue-950";
        const textClass = isComplete
          ? "min-w-0 flex-1 break-words text-sm leading-relaxed text-green-800 dark:text-green-200"
          : isFailed
            ? "min-w-0 flex-1 break-words text-sm leading-relaxed text-red-800 dark:text-red-200"
            : "min-w-0 flex-1 break-words text-sm leading-relaxed text-blue-800 dark:text-blue-200";
        const closeClass = isComplete
          ? "inline-flex size-8 items-center justify-center rounded-md text-green-500 transition-colors hover:bg-green-100 dark:hover:bg-green-900"
          : isFailed
            ? "inline-flex size-8 items-center justify-center rounded-md text-red-500 transition-colors hover:bg-red-100 dark:hover:bg-red-900"
            : "inline-flex size-8 items-center justify-center rounded-md text-blue-500 transition-colors hover:bg-blue-100 dark:hover:bg-blue-900";
        const cardKey = `${authCard.provider}:${authCard.oauth2State ?? authCard.authUrl}`;

        return (
          <div
            key={cardKey}
            data-slot="auth-card"
            data-provider={authCard.provider ?? undefined}
            className={cardClass}
          >
            <div className="flex min-w-0 flex-1 items-start gap-3">
              {isComplete ? (
                <CheckCircleIcon className="mt-0.5 size-5 shrink-0 text-green-600 dark:text-green-400" />
              ) : isFailed ? (
                <AlertCircleIcon className="mt-0.5 size-5 shrink-0 text-red-600 dark:text-red-400" />
              ) : (
                <ShieldCheckIcon className="mt-0.5 size-5 shrink-0 text-blue-600 dark:text-blue-400" />
              )}
              <p className={textClass}>{authCard.message}</p>
            </div>
            <div className="flex shrink-0 items-center gap-2 self-end sm:self-auto">
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
                  href={authCard.authUrl ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex h-8 items-center rounded-md bg-blue-600 px-3 text-sm font-medium text-white transition-colors hover:bg-blue-700"
                >
                  点击授权
                </a>
              )}
              <button
                type="button"
                onClick={() =>
                  clearAuth(
                    authCard.messageId ?? undefined,
                    authCard.provider ?? undefined,
                    authCard.oauth2State,
                    authCard.authUrl,
                  )
                }
                className={closeClass}
                aria-label={`关闭 ${authCard.provider ?? ""} 授权卡片`}
              >
                <XIcon className="size-4" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
};
