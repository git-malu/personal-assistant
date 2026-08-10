import { beforeEach, describe, expect, it } from "vitest";
import { useReportProgressStore } from "./report-progress-store";

describe("report progress store", () => {
  beforeEach(() => {
    useReportProgressStore.getState().clearProgress();
  });

  it("keeps source progress and ignores duplicate or older sequences", () => {
    const store = useReportProgressStore.getState();
    store.setProgress("report-message", {
      sequence: 1,
      source: "github",
      stage: "activity_search",
      status: "running",
      current: 1,
      discovered: 12,
    });
    store.setProgress("report-message", {
      sequence: 2,
      source: "email",
      stage: "email_collection",
      status: "running",
      current: 1,
      total: 2,
    });
    store.setProgress("report-message", {
      sequence: 1,
      source: "github",
      stage: "activity_search",
      status: "running",
      current: 0,
      discovered: 0,
    });

    const entry =
      useReportProgressStore.getState().progressByMessageId["report-message"];
    expect(entry.sequence).toBe(2);
    expect(entry.sources.github).toMatchObject({
      current: 1,
      discovered: 12,
    });
    expect(entry.sources.email).toMatchObject({ current: 1, total: 2 });
  });

  it("isolates messages and prevents terminal progress from reappearing", () => {
    const store = useReportProgressStore.getState();
    store.setProgress("first-message", {
      sequence: 1,
      stage: "preparing",
      status: "running",
    });
    store.setProgress("second-message", {
      sequence: 1,
      stage: "rendering",
      status: "running",
    });
    store.finishProgress("first-message");
    store.setProgress("first-message", {
      sequence: 99,
      source: "github",
      stage: "activity_detail",
      status: "running",
      current: 99,
      total: 100,
    });

    const entries = useReportProgressStore.getState().progressByMessageId;
    expect(entries["first-message"]).toMatchObject({
      sequence: 1,
      terminal: true,
    });
    expect(entries["first-message"].sources.github).toBeUndefined();
    expect(entries["second-message"]).toMatchObject({
      sequence: 1,
      terminal: false,
      global: { stage: "rendering" },
    });
  });

  it("creates a terminal tombstone when report_ready arrives first", () => {
    const store = useReportProgressStore.getState();

    store.finishProgress("report-message", undefined, {
      createIfMissing: true,
    });
    store.setProgress("report-message", {
      sequence: 1,
      source: "github",
      stage: "activity_detail",
      status: "running",
    });

    expect(
      useReportProgressStore.getState().progressByMessageId["report-message"],
    ).toMatchObject({ sequence: 0, terminal: true });
  });

  it("does not create a terminal entry for a generic completion", () => {
    useReportProgressStore.getState().finishProgress("ordinary-message");

    expect(
      useReportProgressStore.getState().progressByMessageId,
    ).not.toHaveProperty("ordinary-message");
  });

  it("normalizes invalid counters without rejecting a valid event", () => {
    useReportProgressStore.getState().setProgress("report-message", {
      sequence: 1,
      source: "github",
      stage: "activity_search",
      status: "running",
      current: -1,
      total: Number.POSITIVE_INFINITY,
      discovered: 7.8,
    });

    expect(
      useReportProgressStore.getState().progressByMessageId["report-message"]
        .sources.github,
    ).toMatchObject({
      current: undefined,
      total: undefined,
      discovered: 7,
    });
  });
});
