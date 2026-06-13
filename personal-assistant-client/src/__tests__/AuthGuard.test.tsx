import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { InteractionStatus } from "@azure/msal-browser";

const mockUseIsAuthenticated = vi.fn();
const mockUseMsal = vi.fn();

vi.mock("@azure/msal-react", () => ({
  useIsAuthenticated: () => mockUseIsAuthenticated(),
  useMsal: () => mockUseMsal(),
}));

vi.mock("@/components/landing/LoadingState", () => ({
  LoadingState: () => <div data-testid="loading-state">Loading...</div>,
}));

import { AuthGuard } from "@/components/landing/AuthGuard";

function setupMsal(inProgress: InteractionStatus, isAuthenticated: boolean) {
  mockUseMsal.mockReturnValue({ inProgress });
  mockUseIsAuthenticated.mockReturnValue(isAuthenticated);
}

describe("AuthGuard", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("InteractionStatus.Startup → renders LoadingState", () => {
    setupMsal(InteractionStatus.Startup, false);
    render(<AuthGuard><div data-testid="child">Child</div></AuthGuard>);
    expect(screen.getByTestId("loading-state")).toBeInTheDocument();
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
  });

  it("InteractionStatus.HandleRedirect → renders LoadingState", () => {
    setupMsal(InteractionStatus.HandleRedirect, false);
    render(<AuthGuard><div data-testid="child">Child</div></AuthGuard>);
    expect(screen.getByTestId("loading-state")).toBeInTheDocument();
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
  });

  it("InteractionStatus.None + isAuthenticated=false → renders children", () => {
    setupMsal(InteractionStatus.None, false);
    render(<AuthGuard><div data-testid="child">Child</div></AuthGuard>);
    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.queryByTestId("loading-state")).not.toBeInTheDocument();
  });

  it("InteractionStatus.None + isAuthenticated=true → renders children", () => {
    setupMsal(InteractionStatus.None, true);
    render(<AuthGuard><div data-testid="child">Child</div></AuthGuard>);
    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.queryByTestId("loading-state")).not.toBeInTheDocument();
  });

  it("InteractionStatus.AcquireToken + authenticated → renders children (does NOT trigger loading)", () => {
    setupMsal(InteractionStatus.AcquireToken, true);
    render(<AuthGuard><div data-testid="child">Child</div></AuthGuard>);
    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.queryByTestId("loading-state")).not.toBeInTheDocument();
  });

  it("InteractionStatus.AcquireToken + NOT authenticated → renders LoadingState", () => {
    setupMsal(InteractionStatus.AcquireToken, false);
    render(<AuthGuard><div data-testid="child">Child</div></AuthGuard>);
    expect(screen.getByTestId("loading-state")).toBeInTheDocument();
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
  });
});
