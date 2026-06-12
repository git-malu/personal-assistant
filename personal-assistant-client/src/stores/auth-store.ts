import { create } from "zustand";

interface AuthState {
  idToken: string | null;
  setIdToken: (token: string | null) => void;
  clearToken: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  idToken: null,
  setIdToken: (token) => set({ idToken: token }),
  clearToken: () => set({ idToken: null }),
}));
