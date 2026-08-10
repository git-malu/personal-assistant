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
  cardsByMessageId: Record<string, AuthCardEntry[]>;
  setAuth: (
    messageId: string,
    provider: string,
    url: string,
    message: string,
    oauth2State?: string | null,
  ) => void;
  setAuthComplete: (
    messageId: string,
    provider: string,
    message?: string,
    oauth2State?: string | null,
  ) => void;
  setAuthFailed: (
    messageId: string,
    provider: string,
    message?: string,
    oauth2State?: string | null,
  ) => void;
  clearAuth: (
    messageId?: string,
    provider?: string,
    oauth2State?: string | null,
    authUrl?: string | null,
  ) => void;
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
  cardsByMessageId: Record<string, AuthCardEntry[]>,
): AuthCardEntry {
  const cardGroups = Object.values(cardsByMessageId);
  for (let index = cardGroups.length - 1; index >= 0; index -= 1) {
    const cards = cardGroups[index];
    if (cards?.length) {
      return cards[cards.length - 1] ?? emptyAuthCard;
    }
  }
  return emptyAuthCard;
}

function normalizeOAuth2State(oauth2State?: string | null): string | null {
  return oauth2State || null;
}

function matchesAuthRequest(
  card: AuthCardEntry,
  provider: string,
  authUrl: string,
  oauth2State?: string | null,
): boolean {
  if (card.provider !== provider) return false;
  const normalizedState = normalizeOAuth2State(oauth2State);
  if (normalizedState) return card.oauth2State === normalizedState;
  return !card.oauth2State && card.authUrl === authUrl;
}

function matchesAuthStatus(
  card: AuthCardEntry,
  provider: string,
  oauth2State?: string | null,
): boolean {
  if (!card.authUrl || card.provider !== provider) return false;
  const normalizedState = normalizeOAuth2State(oauth2State);
  return !normalizedState || card.oauth2State === normalizedState;
}

function matchesAuthIdentity(
  card: AuthCardEntry,
  provider: string,
  oauth2State?: string | null,
  authUrl?: string | null,
): boolean {
  if (card.provider !== provider) return false;
  const normalizedState = normalizeOAuth2State(oauth2State);
  if (normalizedState) return card.oauth2State === normalizedState;
  if (authUrl) return !card.oauth2State && card.authUrl === authUrl;
  return true;
}

function findLatestProviderCard(
  cards: AuthCardEntry[],
  provider: string,
  oauth2State?: string | null,
): number | undefined {
  for (let cardIndex = cards.length - 1; cardIndex >= 0; cardIndex -= 1) {
    const card = cards[cardIndex];
    if (card && matchesAuthStatus(card, provider, oauth2State)) {
      return cardIndex;
    }
  }
  return undefined;
}

export const useAuthCardStore = create<AuthCardState>((set) => ({
  ...emptyAuthCard,
  cardsByMessageId: {},
  setAuth: (messageId, provider, url, message, oauth2State) =>
    set((state) => {
      const normalizedState = normalizeOAuth2State(oauth2State);
      const card: AuthCardEntry = {
        messageId,
        provider,
        authUrl: url,
        message,
        oauth2State: normalizedState,
        authComplete: false,
        authFailed: false,
      };
      const currentCards = state.cardsByMessageId[messageId] ?? [];
      const existingIndex = currentCards.findIndex((currentCard) =>
        matchesAuthRequest(currentCard, provider, url, normalizedState),
      );
      const messageCards = [...currentCards];
      if (existingIndex >= 0) {
        messageCards[existingIndex] = card;
      } else {
        messageCards.push(card);
      }
      return {
        ...card,
        cardsByMessageId: {
          ...state.cardsByMessageId,
          [messageId]: messageCards,
        },
      };
    }),
  setAuthComplete: (messageId, provider, message, oauth2State) =>
    set((state) => {
      const messageCards = state.cardsByMessageId[messageId];
      if (!messageCards) {
        return state;
      }
      const cardIndex = findLatestProviderCard(
        messageCards,
        provider,
        oauth2State,
      );
      if (cardIndex === undefined) {
        return state;
      }

      const currentCard = messageCards[cardIndex];
      if (!currentCard) {
        return state;
      }

      const updatedCard: AuthCardEntry = {
        ...currentCard,
        authComplete: true,
        authFailed: false,
        message: message ?? currentCard.message,
      };
      const updatedMessageCards = [...messageCards];
      updatedMessageCards[cardIndex] = updatedCard;
      const cardsByMessageId = {
        ...state.cardsByMessageId,
        [messageId]: updatedMessageCards,
      };
      return {
        ...pickLatestCard(cardsByMessageId),
        cardsByMessageId,
      };
    }),
  setAuthFailed: (messageId, provider, message, oauth2State) =>
    set((state) => {
      const messageCards = state.cardsByMessageId[messageId];
      if (!messageCards) {
        return state;
      }
      const cardIndex = findLatestProviderCard(
        messageCards,
        provider,
        oauth2State,
      );
      if (cardIndex === undefined) {
        return state;
      }

      const currentCard = messageCards[cardIndex];
      if (!currentCard) {
        return state;
      }

      const updatedCard: AuthCardEntry = {
        ...currentCard,
        authComplete: false,
        authFailed: true,
        message: message ?? currentCard.message,
      };
      const updatedMessageCards = [...messageCards];
      updatedMessageCards[cardIndex] = updatedCard;
      const cardsByMessageId = {
        ...state.cardsByMessageId,
        [messageId]: updatedMessageCards,
      };
      return {
        ...pickLatestCard(cardsByMessageId),
        cardsByMessageId,
      };
    }),
  clearAuth: (messageId, provider, oauth2State, authUrl) =>
    set((state) => {
      if (!messageId) {
        return {
          ...emptyAuthCard,
          cardsByMessageId: {},
        };
      }

      const cardsByMessageId = { ...state.cardsByMessageId };
      if (!provider) {
        delete cardsByMessageId[messageId];
      } else {
        const messageCards = cardsByMessageId[messageId];
        if (!messageCards) return state;
        let cardIndex = -1;
        for (let index = messageCards.length - 1; index >= 0; index -= 1) {
          const card = messageCards[index];
          if (
            card &&
            matchesAuthIdentity(card, provider, oauth2State, authUrl)
          ) {
            cardIndex = index;
            break;
          }
        }
        if (cardIndex < 0) return state;

        const remainingCards = [...messageCards];
        remainingCards.splice(cardIndex, 1);
        if (remainingCards.length) {
          cardsByMessageId[messageId] = remainingCards;
        } else {
          delete cardsByMessageId[messageId];
        }
      }
      const latestCard = pickLatestCard(cardsByMessageId);
      return {
        ...latestCard,
        cardsByMessageId,
      };
    }),
}));
