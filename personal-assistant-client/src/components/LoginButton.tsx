import { useMsal, useIsAuthenticated } from "@azure/msal-react";
import { loginRequest } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { LogIn, LogOut } from "lucide-react";

export function LoginButton() {
  const { instance } = useMsal();
  const isAuthenticated = useIsAuthenticated();

  // Dev mode: MSAL not configured → skip OAuth
  if (!import.meta.env.VITE_ENTRA_CLIENT_ID) {
    return (
      <span className="text-xs text-muted-foreground">
        Dev Mode — Proxy auth enabled
      </span>
    );
  }

  const handleLogin = async () => {
    try {
      await instance.loginPopup(loginRequest);
      // MSAL LOGIN_SUCCESS event → zustand auto-synced (see main.tsx)
    } catch (e) {
      console.error("Login failed:", e);
    }
  };

  const handleLogout = async () => {
    await instance.logoutPopup();
    // MSAL LOGOUT_SUCCESS event → zustand cleared (see main.tsx)
  };

  if (isAuthenticated) {
    return (
      <Button variant="outline" size="sm" onClick={handleLogout}>
        <LogOut className="mr-2 h-4 w-4" />
        Logout
      </Button>
    );
  }

  return (
    <Button variant="default" size="sm" onClick={handleLogin}>
      <LogIn className="mr-2 h-4 w-4" />
      Sign in with Microsoft
    </Button>
  );
}
