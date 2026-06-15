import { describe, it, expect, beforeEach } from "vitest";
import { useAuthStore } from "./auth-store";

describe("useAuthStore", () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    useAuthStore.getState().clearToken();
  });

  it("has idToken null initially", () => {
    expect(useAuthStore.getState().idToken).toBeNull();
  });

  it("setIdToken sets the token", () => {
    useAuthStore.getState().setIdToken("token-abc");
    expect(useAuthStore.getState().idToken).toBe("token-abc");
  });

  it("setIdToken(null) sets idToken to null", () => {
    useAuthStore.getState().setIdToken("token-abc");
    expect(useAuthStore.getState().idToken).toBe("token-abc");
    useAuthStore.getState().setIdToken(null);
    expect(useAuthStore.getState().idToken).toBeNull();
  });

  it("clearToken sets idToken to null", () => {
    useAuthStore.getState().setIdToken("token-xyz");
    expect(useAuthStore.getState().idToken).toBe("token-xyz");
    useAuthStore.getState().clearToken();
    expect(useAuthStore.getState().idToken).toBeNull();
  });

  it("does NOT expose isAuthenticated (auth state belongs to MSAL)", () => {
    const state = useAuthStore.getState();
    // Assert that isAuthenticated is not a key of the store state
    expect(state).not.toHaveProperty("isAuthenticated");
    // The expected keys: idToken, setIdToken, clearToken, hydrated, setHydrated
    expect(Object.keys(state).sort()).toEqual(
      ["clearToken", "hydrated", "idToken", "setHydrated", "setIdToken"].sort(),
    );
  });
});
