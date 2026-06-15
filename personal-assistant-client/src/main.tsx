import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MsalProvider } from "@azure/msal-react";
import { EventType, type AuthenticationResult } from "@azure/msal-browser";
import { msalInstance, acquireIdTokenSilently } from "@/lib/auth";
import { useAuthStore } from "@/stores/auth-store";
import App from "./App";
import "./index.css";

msalInstance.initialize().then(() => {
  // Sync MSAL events → zustand idToken
  msalInstance.addEventCallback((event) => {
    if (event.eventType === EventType.LOGIN_SUCCESS && event.payload) {
      const idToken = (event.payload as AuthenticationResult)?.idToken;
      useAuthStore.getState().setIdToken(idToken);
    }
    if (event.eventType === EventType.LOGOUT_SUCCESS) {
      useAuthStore.getState().clearToken();
    }
  });

  // Safety net: handle any residual redirect response
  msalInstance.handleRedirectPromise().then(async (response) => {
    if (response?.idToken) {
      useAuthStore.getState().setIdToken(response.idToken);
    } else {
      // No redirect in progress — load existing token from MSAL cache (sessionStorage)
      const cachedToken = await acquireIdTokenSilently();
      if (cachedToken) {
        useAuthStore.getState().setIdToken(cachedToken);
      }
    }
    useAuthStore.getState().setHydrated(true);
  });

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <MsalProvider instance={msalInstance}>
        <App />
      </MsalProvider>
    </StrictMode>
  );
});
