import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useReportProgressStore } from "@/stores/report-progress-store";
import { ReportProgressCard } from "./ReportProgressCard";

describe("ReportProgressCard", () => {
  beforeEach(() => {
    useReportProgressStore.getState().clearProgress();
  });

  it("renders only inside the assistant message that owns the progress", () => {
    useReportProgressStore.getState().setProgress("report-message", {
      sequence: 1,
      stage: "preparing",
      status: "running",
    });

    const { rerender } = render(
      <ReportProgressCard messageId="other-message" />,
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    rerender(<ReportProgressCard messageId="report-message" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-sequence", "1");
    expect(screen.getByText("准备数据源")).toBeInTheDocument();
  });

  it("keeps source rows ordered and shows real detail counts", () => {
    const store = useReportProgressStore.getState();
    store.setProgress("report-message", {
      sequence: 1,
      source: "calendar",
      stage: "calendar_collection",
      status: "running",
      current: 0,
      total: 1,
    });
    store.setProgress("report-message", {
      sequence: 2,
      source: "github",
      stage: "activity_detail",
      status: "running",
      current: 18,
      total: 37,
      discovered: 37,
    });
    store.setProgress("report-message", {
      sequence: 3,
      source: "email",
      stage: "email_collection",
      status: "complete",
      current: 2,
      total: 2,
      discovered: 4,
    });

    render(<ReportProgressCard messageId="report-message" />);

    const rows = screen.getAllByRole("listitem");
    expect(rows.map((row) => row.getAttribute("data-source"))).toEqual([
      "github",
      "email",
      "calendar",
    ]);
    expect(within(rows[0]).getByText("18 / 37")).toBeInTheDocument();
    expect(within(rows[1]).getByText("2 / 2")).toBeInTheDocument();
  });

  it("uses an indeterminate status when the search total is unknown", () => {
    useReportProgressStore.getState().setProgress("report-message", {
      sequence: 1,
      source: "github",
      stage: "activity_search",
      status: "running",
      current: 3,
      discovered: 37,
    });

    render(<ReportProgressCard messageId="report-message" />);

    expect(screen.getByText("已发现 37 项")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("disappears permanently after report_ready marks the entry terminal", () => {
    const store = useReportProgressStore.getState();
    store.setProgress("report-message", {
      sequence: 1,
      stage: "rendering",
      status: "running",
    });
    const { rerender } = render(
      <ReportProgressCard messageId="report-message" />,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();

    useReportProgressStore.getState().finishProgress("report-message");
    rerender(<ReportProgressCard messageId="report-message" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    useReportProgressStore.getState().setProgress("report-message", {
      sequence: 2,
      source: "github",
      stage: "activity_detail",
      status: "running",
    });
    rerender(<ReportProgressCard messageId="report-message" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
