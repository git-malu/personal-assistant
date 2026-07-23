import { useIsAuthenticated } from "@azure/msal-react";
import React, { Suspense } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { AuthGuard } from "@/components/landing/AuthGuard";
import { LoadingState } from "@/components/landing/LoadingState";
import { ChunkErrorBoundary } from "@/components/landing/ChunkErrorBoundary";
import { getPublicConfig } from "@/config";

const ChatPage = React.lazy(() => import("./components/chat/ChatPage"));
const LandingPage = React.lazy(() => import("./components/landing/LandingPage"));
const M365CalendarCallbackPage = React.lazy(
  () => import("./components/auth/M365CalendarCallbackPage"),
);

function App() {
  const isAuthenticated = useIsAuthenticated();
  const hydrated = useAuthStore((s) => s.hydrated);
  const idToken = useAuthStore((s) => s.idToken);
  const isLocalDev = import.meta.env.DEV && !getPublicConfig().isEntraEnabled;
  const canShowChat = isLocalDev || (isAuthenticated && Boolean(idToken));
  const isCalendarCallback =
    window.location.pathname === "/auth/callback/m365-calendar";

  if (isCalendarCallback) {
    return (
      <ChunkErrorBoundary>
        <Suspense fallback={<LoadingState />}>
          <M365CalendarCallbackPage />
        </Suspense>
      </ChunkErrorBoundary>
    );
  }

  return (
    <AuthGuard>
      <ChunkErrorBoundary>
        <Suspense fallback={<LoadingState />}>
          {!hydrated ? <LoadingState /> :
           canShowChat ? <ChatPage /> : <LandingPage />}
        </Suspense>
      </ChunkErrorBoundary>
    </AuthGuard>
  );
}

export default App;
