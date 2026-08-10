import type {
  ReportProgressPayload,
  ReportProgressSource,
} from "@/types/chat";
import { create } from "zustand";

export interface ReportProgressEntry {
  sequence: number;
  terminal: boolean;
  global?: ReportProgressPayload;
  sources: Partial<Record<ReportProgressSource, ReportProgressPayload>>;
}

interface FinishProgressOptions {
  createIfMissing?: boolean;
}

interface ReportProgressState {
  progressByMessageId: Record<string, ReportProgressEntry>;
  setProgress: (messageId: string, progress: ReportProgressPayload) => void;
  finishProgress: (
    messageId: string,
    sequence?: number,
    options?: FinishProgressOptions,
  ) => void;
  clearProgress: (messageId?: string) => void;
}

function normalizeCount(value: number | undefined): number | undefined {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return undefined;
  }
  return Math.floor(value);
}

function normalizeProgress(
  progress: ReportProgressPayload,
): ReportProgressPayload {
  return {
    ...progress,
    current: normalizeCount(progress.current),
    total: normalizeCount(progress.total),
    discovered: normalizeCount(progress.discovered),
  };
}

export const useReportProgressStore = create<ReportProgressState>((set) => ({
  progressByMessageId: {},
  setProgress: (messageId, progress) =>
    set((state) => {
      if (!Number.isInteger(progress.sequence) || progress.sequence < 1) {
        return state;
      }
      const currentEntry = state.progressByMessageId[messageId];
      if (
        currentEntry?.terminal ||
        (currentEntry && progress.sequence <= currentEntry.sequence)
      ) {
        return state;
      }

      const normalized = normalizeProgress(progress);
      const nextEntry: ReportProgressEntry = {
        sequence: normalized.sequence,
        terminal: false,
        global: currentEntry?.global,
        sources: currentEntry?.sources ?? {},
      };
      if (normalized.source) {
        nextEntry.sources = {
          ...nextEntry.sources,
          [normalized.source]: normalized,
        };
      } else {
        nextEntry.global = normalized;
      }

      return {
        progressByMessageId: {
          ...state.progressByMessageId,
          [messageId]: nextEntry,
        },
      };
    }),
  finishProgress: (messageId, sequence, options) =>
    set((state) => {
      const currentEntry = state.progressByMessageId[messageId];
      if (!currentEntry && !options?.createIfMissing) {
        return state;
      }
      const terminalSequence = Math.max(
        currentEntry?.sequence ?? 0,
        typeof sequence === "number" && Number.isFinite(sequence)
          ? Math.floor(sequence)
          : 0,
      );
      return {
        progressByMessageId: {
          ...state.progressByMessageId,
          [messageId]: {
            sequence: terminalSequence,
            terminal: true,
            global: currentEntry?.global,
            sources: currentEntry?.sources ?? {},
          },
        },
      };
    }),
  clearProgress: (messageId) =>
    set((state) => {
      if (!messageId) return { progressByMessageId: {} };
      if (!(messageId in state.progressByMessageId)) return state;
      const progressByMessageId = { ...state.progressByMessageId };
      delete progressByMessageId[messageId];
      return { progressByMessageId };
    }),
}));
