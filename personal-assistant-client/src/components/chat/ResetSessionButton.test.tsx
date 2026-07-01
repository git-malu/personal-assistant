import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TooltipProvider } from "@/components/ui/tooltip";

// ────────────────────────────────────────────────────
// 1. Create hoisted mock functions so vi.mock can reference them
// ────────────────────────────────────────────────────
const { mockUseAui, mockUseAuiState, mockResetSessionId } = vi.hoisted(() => ({
  mockUseAui: vi.fn(),
  mockUseAuiState: vi.fn(),
  mockResetSessionId: vi.fn(),
}));

// ────────────────────────────────────────────────────
// 2. Mock external modules
// ────────────────────────────────────────────────────
vi.mock("@assistant-ui/react", () => ({
  useAui: mockUseAui,
  useAuiState: mockUseAuiState,
}));

vi.mock("@/lib/chat-adapter", () => ({
  resetSessionId: mockResetSessionId,
}));

// ────────────────────────────────────────────────────
// 3. Import component under test
// ────────────────────────────────────────────────────
import { ResetSessionButton } from "./ResetSessionButton";

// ────────────────────────────────────────────────────
// 4. Shared mock infrastructure
// ────────────────────────────────────────────────────
const mockCancelRun = vi.fn();
const mockThreadReset = vi.fn();
const mockComposerReset = vi.fn().mockResolvedValue(undefined);
const mockSwitchToNewThread = vi.fn().mockResolvedValue(undefined);
const mockGetThreadItem = vi.fn();
const mockInitializeThreadListItem = vi.fn().mockResolvedValue(undefined);
const mockGetAssistantRuntime = vi.fn();
const mockRuntimeSwitchToNewThread = vi.fn().mockResolvedValue(undefined);
const mockRuntimeInitializeMainItem = vi.fn().mockResolvedValue(undefined);
const mockThread = vi.fn(() => ({
  cancelRun: mockCancelRun,
  reset: mockThreadReset,
}));
const mockComposer = vi.fn(() => ({
  reset: mockComposerReset,
}));
const mockThreads = vi.fn(() => ({
  switchToNewThread: mockSwitchToNewThread,
  item: mockGetThreadItem,
  __internal_getAssistantRuntime: mockGetAssistantRuntime,
}));

/**
 * Build the standard "not running" AUI mock state.
 */
function setupStandardMocks() {
  mockUseAui.mockReset();
  mockUseAuiState.mockReset();
  mockResetSessionId.mockReset();
  mockCancelRun.mockReset();
  mockThreadReset.mockReset();
  mockComposerReset.mockReset();
  mockSwitchToNewThread.mockReset();
  mockGetThreadItem.mockReset();
  mockInitializeThreadListItem.mockReset();
  mockGetAssistantRuntime.mockReset();
  mockRuntimeSwitchToNewThread.mockReset();
  mockRuntimeInitializeMainItem.mockReset();
  mockThread.mockReset();
  mockComposer.mockReset();
  mockThreads.mockReset();

  mockComposerReset.mockResolvedValue(undefined);
  mockSwitchToNewThread.mockResolvedValue(undefined);
  mockGetThreadItem.mockReturnValue({
    initialize: mockInitializeThreadListItem,
  });
  mockInitializeThreadListItem.mockResolvedValue(undefined);
  mockRuntimeSwitchToNewThread.mockResolvedValue(undefined);
  mockRuntimeInitializeMainItem.mockResolvedValue(undefined);
  mockGetAssistantRuntime.mockReturnValue({
    threads: {
      switchToNewThread: mockRuntimeSwitchToNewThread,
      mainItem: {
        initialize: mockRuntimeInitializeMainItem,
      },
    },
  });
  mockThread.mockReturnValue({
    cancelRun: mockCancelRun,
    reset: mockThreadReset,
  });
  mockComposer.mockReturnValue({
    reset: mockComposerReset,
  });
  mockThreads.mockReturnValue({
    switchToNewThread: mockSwitchToNewThread,
    item: mockGetThreadItem,
    __internal_getAssistantRuntime: mockGetAssistantRuntime,
  });
  mockUseAui.mockReturnValue({
    thread: mockThread,
    composer: mockComposer,
    threads: mockThreads,
  });
  mockUseAuiState.mockReturnValue(false);
}

// ────────────────────────────────────────────────────
// 5. Tests
// ────────────────────────────────────────────────────
describe("ResetSessionButton", () => {
  beforeEach(() => {
    setupStandardMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // ── CT-RS-01: Initial render ──────────────────────
  it("CT-RS-01: renders a ghost icon-sm Button with aria-label and RotateCcw icon, not disabled when not running", () => {
    render(<ResetSessionButton />);

    const button = screen.getByRole("button", { name: "新对话" });
    expect(button).toBeInTheDocument();
    expect(button).not.toBeDisabled();

    // RotateCcw icon should be inside the button
    const icon = button.querySelector("svg");
    expect(icon).toBeInTheDocument();
    // lucide-react class convention
    expect(icon!.classList.toString()).toMatch(/lucide/);
  });

  // ── CT-RS-02: Tooltip display ────────────────────
  it("CT-RS-02: shows Tooltip with text '新对话' on hover", async () => {
    const user = userEvent.setup();
    render(
      <TooltipProvider>
        <ResetSessionButton />
      </TooltipProvider>,
    );

    const button = screen.getByRole("button", { name: "新对话" });

    // Hover over the button to trigger the tooltip
    await user.hover(button);

    // Tooltip content appears in a portal — search entire document
    const tooltip = await screen.findByText("新对话", {}, { timeout: 2000 });
    expect(tooltip).toBeInTheDocument();
  });

  // ── CT-RS-03: Dialog opens on click ──────────────
  it("CT-RS-03: opens Dialog on button click", async () => {
    const user = userEvent.setup();
    render(<ResetSessionButton />);

    const button = screen.getByRole("button", { name: "新对话" });
    await user.click(button);

    // Dialog should be visible — the title "新对话" appears both in
    // the tooltip and the dialog title, but the role="dialog" confirms
    // the dialog is open.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  // ── CT-RS-04: Dialog content verification ────────
  it("CT-RS-04: Dialog has title, description, Cancel and Confirm buttons", async () => {
    const user = userEvent.setup();
    render(<ResetSessionButton />);

    await user.click(screen.getByRole("button", { name: "新对话" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();

    // Title
    expect(screen.getByText("新对话")).toBeInTheDocument();

    // Description
    expect(
      screen.getByText(/开始全新对话/),
    ).toBeInTheDocument();

    // Cancel button
    expect(
      screen.getByRole("button", { name: "取消" }),
    ).toBeInTheDocument();

    // Confirm button (apple-secondary variant)
    const confirmButton = screen.getByRole("button", { name: "确认" });
    expect(confirmButton).toBeInTheDocument();
  });

  // ── CT-RS-05: Cancel has no side effects ─────────
  it("CT-RS-05: clicking Cancel closes dialog without calling resetSessionId or thread methods", async () => {
    const user = userEvent.setup();
    render(<ResetSessionButton />);

    await user.click(screen.getByRole("button", { name: "新对话" }));
    await user.click(screen.getByRole("button", { name: "取消" }));

    // Dialog should close
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // No reset operations should have been called
    expect(mockCancelRun).not.toHaveBeenCalled();
    expect(mockResetSessionId).not.toHaveBeenCalled();
    expect(mockThreadReset).not.toHaveBeenCalled();
    expect(mockComposer).not.toHaveBeenCalled();
  });

  // ── CT-RS-06: Confirm executes full reset sequence ─
  it("CT-RS-06: clicking Confirm creates a new conversation before clearing the legacy session hint", async () => {
    const user = userEvent.setup();
    render(<ResetSessionButton />);

    await user.click(screen.getByRole("button", { name: "新对话" }));
    await user.click(screen.getByRole("button", { name: "确认" }));

    // Wait for the async handleConfirm to finish
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    // All reset and new-conversation operations should have been called once.
    expect(mockCancelRun).toHaveBeenCalledTimes(1);
    expect(mockResetSessionId).toHaveBeenCalledTimes(1);
    expect(mockThreadReset).toHaveBeenCalledTimes(1);
    expect(mockComposer).toHaveBeenCalledTimes(1);
    expect(mockComposerReset).toHaveBeenCalledTimes(1);
    expect(mockThreads).toHaveBeenCalledTimes(1);
    expect(mockRuntimeSwitchToNewThread).toHaveBeenCalledTimes(1);
    expect(mockRuntimeInitializeMainItem).toHaveBeenCalledTimes(1);
    expect(mockSwitchToNewThread).not.toHaveBeenCalled();
    expect(mockInitializeThreadListItem).not.toHaveBeenCalled();

    // Verify order: UI reset → new remote thread → legacy hint cleanup.
    const callOrder = [
      mockCancelRun,
      mockThreadReset,
      mockComposer,
      mockComposerReset,
      mockThreads,
      mockRuntimeSwitchToNewThread,
      mockRuntimeInitializeMainItem,
      mockResetSessionId,
    ].map((m) => m.mock?.invocationCallOrder?.[0] ?? Infinity);

    expect(callOrder[0]).toBeLessThan(callOrder[1]); // cancelRun before thread.reset
    expect(callOrder[1]).toBeLessThan(callOrder[2]); // thread.reset before composer
    expect(callOrder[3]).toBeLessThan(callOrder[4]); // composer.reset before threads
    expect(callOrder[5]).toBeLessThan(callOrder[6]); // switch before initialize
    expect(callOrder[6]).toBeLessThan(callOrder[7]); // initialize before resetSessionId
  });

  // ── CT-RS-07: Button disabled during streaming ───
  it("CT-RS-07: button is disabled when thread.isRunning is true", () => {
    // Override: streaming in progress
    mockUseAuiState.mockReturnValue(true);

    render(<ResetSessionButton />);

    const button = screen.getByRole("button", { name: "新对话" });
    expect(button).toBeDisabled();
  });

  it("CT-RS-07b: falls back to store thread methods when runtime is unavailable", async () => {
    mockGetAssistantRuntime.mockReturnValue(undefined);
    const user = userEvent.setup();
    render(<ResetSessionButton />);

    await user.click(screen.getByRole("button", { name: "新对话" }));
    await user.click(screen.getByRole("button", { name: "确认" }));

    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    expect(mockSwitchToNewThread).toHaveBeenCalledTimes(1);
    expect(mockGetThreadItem).toHaveBeenCalledWith("main");
    expect(mockInitializeThreadListItem).toHaveBeenCalledTimes(1);
    expect(mockResetSessionId).toHaveBeenCalledTimes(1);
  });

  // ── CT-RS-08: Error in composer().reset() does not freeze dialog ─
  it("CT-RS-08: dialog still closes when composer().reset() rejects (finally block)", async () => {
    // Override: composer reset rejects
    mockComposerReset.mockRejectedValueOnce(new Error("composer error"));

    const consoleSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    const user = userEvent.setup();
    render(<ResetSessionButton />);

    await user.click(screen.getByRole("button", { name: "新对话" }));
    await user.click(screen.getByRole("button", { name: "确认" }));

    // Dialog must close despite the error (finally block)
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    // The error should have been logged
    expect(consoleSpy).toHaveBeenCalledWith(
      "Failed during session reset:",
      expect.any(Error),
    );

    consoleSpy.mockRestore();
  });

  // ── CT-RS-09: Works without auth ─────────────────
  it("CT-RS-09: component renders and functions without any auth context", () => {
    // No auth mocks needed — the component does not import or use auth
    expect(() => render(<ResetSessionButton />)).not.toThrow();

    const button = screen.getByRole("button", { name: "新对话" });
    expect(button).toBeInTheDocument();
  });

  // ── CT-RS-10: cancelRun error — no subsequent ops ─
  it("CT-RS-10: when cancelRun() throws, subsequent operations are NOT called and dialog still closes", async () => {
    // cancelRun throws — should NOT proceed to thread.reset / composer.reset / resetSessionId
    mockCancelRun.mockImplementation(() => {
      throw new Error("cancelRun failed");
    });

    const consoleSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    const user = userEvent.setup();
    render(<ResetSessionButton />);

    await user.click(screen.getByRole("button", { name: "新对话" }));
    await user.click(screen.getByRole("button", { name: "确认" }));

    // Dialog must close (finally block)
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    // cancelRun should have been called
    expect(mockCancelRun).toHaveBeenCalledTimes(1);

    // Subsequent operations must NOT have been called
    expect(mockThreadReset).not.toHaveBeenCalled();
    expect(mockComposerReset).not.toHaveBeenCalled();
    expect(mockSwitchToNewThread).not.toHaveBeenCalled();
    expect(mockInitializeThreadListItem).not.toHaveBeenCalled();
    expect(mockResetSessionId).not.toHaveBeenCalled();

    consoleSpy.mockRestore();
  });

  // ── CT-RS-11: thread.reset error — resetSessionId NOT called ─
  it("CT-RS-11: when thread.reset() throws, resetSessionId is NOT called (UI-first ordering, H-02)", async () => {
    // thread.reset throws after cancelRun succeeds
    mockThreadReset.mockImplementation(() => {
      throw new Error("thread reset failed");
    });

    const consoleSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    const user = userEvent.setup();
    render(<ResetSessionButton />);

    await user.click(screen.getByRole("button", { name: "新对话" }));
    await user.click(screen.getByRole("button", { name: "确认" }));

    // Dialog must close (finally block)
    await vi.waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    // cancelRun should have been called
    expect(mockCancelRun).toHaveBeenCalledTimes(1);

    // thread.reset should have been called (it threw)
    expect(mockThreadReset).toHaveBeenCalledTimes(1);

    // H-02 fix: since thread.reset threw, resetSessionId must NOT be called
    // (session ID preserved → user can retry with same session)
    expect(mockSwitchToNewThread).not.toHaveBeenCalled();
    expect(mockInitializeThreadListItem).not.toHaveBeenCalled();
    expect(mockResetSessionId).not.toHaveBeenCalled();

    consoleSpy.mockRestore();
  });
});
