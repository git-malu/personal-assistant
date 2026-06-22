import { createContext, useContext, useEffect, useState } from "react";
import {
  ensureRuntimeSession,
  migrateLegacyConversation,
} from "@/lib/conversations/api";
import {
  getLegacySessionHint,
  resetSessionId,
} from "@/lib/chat/session";

type RuntimeState = "warming" | "ready" | "degraded";

const RuntimeStatusContext = createContext<RuntimeState>("warming");

export function RuntimeStatusProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [status, setStatus] = useState<RuntimeState>("warming");

  useEffect(() => {
    let cancelled = false;
    ensureRuntimeSession()
      .then(async (result) => {
        if (!cancelled) setStatus(result.status);
        const legacySessionId = getLegacySessionHint();
        if (legacySessionId) {
          await migrateLegacyConversation(legacySessionId);
          resetSessionId();
        }
      })
      .catch(() => {
        if (!cancelled) setStatus("degraded");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <RuntimeStatusContext.Provider value={status}>
      {children}
    </RuntimeStatusContext.Provider>
  );
}

export function RuntimeStatus() {
  const status = useContext(RuntimeStatusContext);
  const label = {
    warming: "Runtime 预热中…",
    ready: "Runtime 已就绪",
    degraded: "Runtime 按需启动",
  }[status];
  return (
    <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span
        className={`size-1.5 rounded-full ${
          status === "ready"
            ? "bg-green-500"
            : status === "warming"
              ? "animate-pulse bg-amber-500"
              : "bg-muted-foreground"
        }`}
      />
      {label}
    </span>
  );
}
