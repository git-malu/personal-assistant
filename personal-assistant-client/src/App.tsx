import { useIsAuthenticated } from "@azure/msal-react";
import React, { Suspense } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { AuthGuard } from "@/components/landing/AuthGuard";
import { LoadingState } from "@/components/landing/LoadingState";
import { ChunkErrorBoundary } from "@/components/landing/ChunkErrorBoundary";

const ChatPage = React.lazy(() => import("./components/chat/ChatPage"));
const LandingPage = React.lazy(() => import("./components/landing/LandingPage"));

function App() {
  const isAuthenticated = useIsAuthenticated();
  const hydrated = useAuthStore((s) => s.hydrated);

  return (
    <AuthGuard>
      <ChunkErrorBoundary>
        <Suspense fallback={<LoadingState />}>
          {!hydrated ? <LoadingState /> :
           isAuthenticated ? <ChatPage /> : <LandingPage />}
        </Suspense>
      </ChunkErrorBoundary>
    </AuthGuard>
  );
}

export default App;
