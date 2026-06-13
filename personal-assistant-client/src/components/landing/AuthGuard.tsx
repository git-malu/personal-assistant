import { type ReactNode } from "react";
import { InteractionStatus } from "@azure/msal-browser";
import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import { LoadingState } from "./LoadingState";

export function AuthGuard({ children }: { children: ReactNode }) {
  const { inProgress } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  const isAuthTransition =
    inProgress === InteractionStatus.Startup ||
    inProgress === InteractionStatus.HandleRedirect ||
    (!isAuthenticated && inProgress !== InteractionStatus.None);

  if (isAuthTransition) {
    return <LoadingState />;
  }

  return <>{children}</>;
}
