import { create } from "zustand";

interface AuthState {
  idToken: string | null;
  hydrated: boolean;
  setIdToken: (token: string | null) => void;
  setHydrated: (value: boolean) => void;
  clearToken: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  idToken: null,
  hydrated: false,
  setIdToken: (token) => set({ idToken: token }),
  setHydrated: (value) => set({ hydrated: value }),
  clearToken: () => set({ idToken: null, hydrated: false }),
}));
