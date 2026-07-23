import { create } from "zustand";

interface ConversationListState {
  error: string | null;
  setError: (error: string | null) => void;
}

export const useConversationListStore = create<ConversationListState>((set) => ({
  error: null,
  setError: (error) => set({ error }),
}));
