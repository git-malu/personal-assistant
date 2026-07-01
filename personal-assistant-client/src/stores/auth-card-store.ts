import { create } from "zustand";

export interface AuthCardEntry {
  /** The message ID associated with this auth request */
  messageId: string | null;
  /** OAuth provider associated with the pending authorization request. */
  provider: string | null;
  /** OAuth authorization URL to open in a popup / new tab. */
  authUrl: string | null;
  /** Human-readable message explaining why authorization is needed. */
  message: string;
  /** Signed OAuth2 state for matching backend callback status to this card. */
  oauth2State?: string | null;
  /** Whether the user has completed authorization (green card). */
  authComplete: boolean;
  /** Whether the latest authorization attempt failed (red card). */
  authFailed: boolean;
}

interface AuthCardState extends AuthCardEntry {
  /** Auth cards keyed by their assistant message ID. */
  cardsByMessageId: Record<string, AuthCardEntry>;
  setAuth: (
    messageId: string,
    provider: string,
    url: string,
    message: string,
    oauth2State?: string | null,
  ) => void;
  setAuthComplete: (
    provider: string,
    message?: string,
    oauth2State?: string | null,
  ) => void;
  setAuthFailed: (
    provider: string,
    message?: string,
    oauth2State?: string | null,
  ) => void;
  clearAuth: (messageId?: string) => void;
}

const emptyAuthCard: AuthCardEntry = {
  messageId: null,
  provider: null,
  authUrl: null,
  message: "",
  oauth2State: null,
  authComplete: false,
  authFailed: false,
};

function pickLatestCard(
  cardsByMessageId: Record<string, AuthCardEntry>,
): AuthCardEntry {
  const cards = Object.values(cardsByMessageId);
  return cards[cards.length - 1] ?? emptyAuthCard;
}

function findLatestProviderMessageId(
  cardsByMessageId: Record<string, AuthCardEntry>,
  provider: string,
  oauth2State?: string | null,
): string | undefined {
  return (
    Object.values(cardsByMessageId)
      .reverse()
      .find(
        (card) =>
          card.authUrl &&
          card.provider === provider &&
          (!oauth2State || card.oauth2State === oauth2State),
      )?.messageId ??
    undefined
  );
}

export const useAuthCardStore = create<AuthCardState>((set) => ({
  ...emptyAuthCard,
  cardsByMessageId: {},
  setAuth: (messageId, provider, url, message, oauth2State) =>
    set((state) => {
      const card: AuthCardEntry = {
        messageId,
        provider,
        authUrl: url,
        message,
        oauth2State: oauth2State ?? null,
        authComplete: false,
        authFailed: false,
      };
      return {
        ...card,
        cardsByMessageId: {
          ...state.cardsByMessageId,
          [messageId]: card,
        },
      };
    }),
  setAuthComplete: (provider, message, oauth2State) =>
    set((state) => {
      const messageId = findLatestProviderMessageId(
        state.cardsByMessageId,
        provider,
        oauth2State,
      );
      if (!messageId) {
        return state;
      }

      const currentCard = state.cardsByMessageId[messageId];
      if (!currentCard) {
        return state;
      }

      const updatedCard: AuthCardEntry = {
        ...currentCard,
        authComplete: true,
        authFailed: false,
        message: message ?? currentCard.message,
      };
      const cardsByMessageId = {
        ...state.cardsByMessageId,
        [messageId]: updatedCard,
      };
      const latestCard =
        state.messageId === messageId
          ? updatedCard
          : pickLatestCard(cardsByMessageId);
      return {
        ...latestCard,
        cardsByMessageId,
      };
    }),
  setAuthFailed: (provider, message, oauth2State) =>
    set((state) => {
      const messageId = findLatestProviderMessageId(
        state.cardsByMessageId,
        provider,
        oauth2State,
      );
      if (!messageId) {
        return state;
      }

      const currentCard = state.cardsByMessageId[messageId];
      if (!currentCard) {
        return state;
      }

      const updatedCard: AuthCardEntry = {
        ...currentCard,
        authComplete: false,
        authFailed: true,
        message: message ?? currentCard.message,
      };
      const cardsByMessageId = {
        ...state.cardsByMessageId,
        [messageId]: updatedCard,
      };
      const latestCard =
        state.messageId === messageId
          ? updatedCard
          : pickLatestCard(cardsByMessageId);
      return {
        ...latestCard,
        cardsByMessageId,
      };
    }),
  clearAuth: (messageId) =>
    set((state) => {
      if (!messageId) {
        return {
          ...emptyAuthCard,
          cardsByMessageId: {},
        };
      }

      const cardsByMessageId = { ...state.cardsByMessageId };
      delete cardsByMessageId[messageId];
      const latestCard = pickLatestCard(cardsByMessageId);
      return {
        ...latestCard,
        cardsByMessageId,
      };
    }),
}));
