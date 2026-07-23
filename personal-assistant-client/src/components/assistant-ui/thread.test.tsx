import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CancellationAction, guardComposerSubmission } from "./thread";

describe("CancellationAction", () => {
  it("keeps a disabled stop control visible while cancellation is pending", () => {
    render(<CancellationAction status="cancelling" onRetry={vi.fn()} />);

    const button = screen.getByRole("button", { name: "Stopping response" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("data-cancellation-state", "cancelling");
    expect(
      screen.queryByRole("button", { name: "Send message" }),
    ).not.toBeInTheDocument();
  });

  it("offers an explicit stop retry after cancellation fails", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<CancellationAction status="cancel_failed" onRetry={onRetry} />);

    const button = screen.getByRole("button", { name: "Retry stop" });
    expect(button).toBeEnabled();
    expect(button).toHaveAttribute("data-cancellation-state", "cancel_failed");

    await user.click(button);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("cancellation submission guard", () => {
  it.each(["cancelling", "cancel_failed"] as const)(
    "prevents form submission while status is %s",
    (status) => {
      const preventDefault = vi.fn();

      guardComposerSubmission(status, { preventDefault });

      expect(preventDefault).toHaveBeenCalledTimes(1);
    },
  );

  it("allows form submission when no cancellation is pending", () => {
    const preventDefault = vi.fn();

    guardComposerSubmission("idle", { preventDefault });

    expect(preventDefault).not.toHaveBeenCalled();
  });
});
