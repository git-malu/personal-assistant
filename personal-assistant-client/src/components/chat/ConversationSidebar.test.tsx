import { fireEvent, render, screen } from "@testing-library/react";
import type { MouseEvent, ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const assistantUi = vi.hoisted(() => ({
  switchTo: vi.fn(() => Promise.resolve()),
}));

vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    threadListItem: () => ({ switchTo: assistantUi.switchTo }),
  }),
  useAuiState: (selector: (state: object) => unknown) =>
    selector({ threadListItem: { title: "Archived conversation" } }),
  ThreadListItemPrimitive: {
    Root: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    Trigger: ({
      children,
      onClick,
    }: {
      children: ReactNode;
      onClick?: (event: MouseEvent<HTMLButtonElement>) => void;
    }) => (
      <button
        type="button"
        onClick={(event) => {
          onClick?.(event);
          if (!event.defaultPrevented) void assistantUi.switchTo();
        }}
      >
        {children}
      </button>
    ),
    Title: ({ fallback }: { fallback: string }) => <>{fallback}</>,
  },
  ThreadListItemMorePrimitive: {
    Root: () => null,
    Trigger: () => null,
    Content: () => null,
    Item: () => null,
  },
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }: { children: ReactNode }) => <>{children}</>,
  DialogClose: () => null,
  DialogContent: () => null,
  DialogDescription: () => null,
  DialogFooter: () => null,
  DialogHeader: () => null,
  DialogTitle: () => null,
  DialogTrigger: () => null,
}));

import { ConversationListItem } from "./ConversationSidebar";

describe("ConversationListItem", () => {
  beforeEach(() => {
    assistantUi.switchTo.mockClear();
  });

  it("opens archived history without implicitly restoring it", () => {
    const onNavigate = vi.fn();
    render(<ConversationListItem archived onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole("button", { name: "新对话" }));

    expect(assistantUi.switchTo).toHaveBeenCalledTimes(1);
    expect(assistantUi.switchTo).toHaveBeenCalledWith({ unarchive: false });
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("retains the primitive default switch for active history", () => {
    render(<ConversationListItem archived={false} />);

    fireEvent.click(screen.getByRole("button", { name: "新对话" }));

    expect(assistantUi.switchTo).toHaveBeenCalledTimes(1);
    expect(assistantUi.switchTo).toHaveBeenCalledWith();
  });
});
