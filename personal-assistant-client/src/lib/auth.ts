import { PublicClientApplication, type Configuration } from "@azure/msal-browser";

const msalConfig: Configuration = {
  auth: {
    clientId: import.meta.env.VITE_ENTRA_CLIENT_ID ?? "",
    authority: `https://login.microsoftonline.com/${import.meta.env.VITE_ENTRA_TENANT_ID ?? "common"}`,
    redirectUri: typeof window !== "undefined" ? window.location.origin : "",
  },
  cache: {
    cacheLocation: "sessionStorage", // Required by loginRedirect (redirect destroys memory)
  },
};

export const msalInstance = new PublicClientApplication(msalConfig);

export const loginRequest = {
  scopes: ["openid", "profile", "email", "User.Read"],
};

export async function acquireIdTokenSilently(): Promise<string | null> {
  try {
    const accounts = msalInstance.getAllAccounts();
    if (accounts.length === 0) return null;
    const response = await msalInstance.acquireTokenSilent({
      scopes: ["openid", "profile", "email"],
      account: accounts[0],
    });
    return response.idToken;
  } catch (e) {
    console.warn("acquireIdTokenSilently failed:", e);
    return null;
  }
}

/** Fetch the current user's Microsoft 365 profile photo (max 96×96).
 *  Returns a data URL string, or null if the user has no photo or the call fails. */
export async function fetchUserPhoto(): Promise<string | null> {
  try {
    const accounts = msalInstance.getAllAccounts();
    if (accounts.length === 0) return null;

    const tokenResponse = await msalInstance.acquireTokenSilent({
      scopes: ["User.Read"],
      account: accounts[0],
    });

    const res = await fetch("https://graph.microsoft.com/v1.0/me/photo/$value", {
      headers: { Authorization: `Bearer ${tokenResponse.accessToken}` },
    });
    if (!res.ok) return null;

    const blob = await res.blob();
    return URL.createObjectURL(blob);
  } catch {
    return null;
  }
}
