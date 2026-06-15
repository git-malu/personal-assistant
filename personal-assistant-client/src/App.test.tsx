import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { InteractionStatus } from "@azure/msal-browser";
import { useAuthStore } from "@/stores/auth-store";

// Mock lazy-loaded chunks with simple test markers
vi.mock("./components/chat/ChatPage", () => ({
  default: () => <div data-testid="chat-page">ChatPage</div>,
}));

vi.mock("./components/landing/LandingPage", () => ({
  default: () => <div data-testid="landing-page">LandingPage</div>,
}));

// Mock @azure/msal-react hooks
const mockUseIsAuthenticated = vi.fn();
const mockUseMsal = vi.fn();

vi.mock("@azure/msal-react", () => ({
  useIsAuthenticated: () => mockUseIsAuthenticated(),
  useMsal: () => mockUseMsal(),
}));

import App from "./App";

function setupAuth(isAuthenticated: boolean, hydrated: boolean) {
  mockUseIsAuthenticated.mockReturnValue(isAuthenticated);
  mockUseMsal.mockReturnValue({ inProgress: InteractionStatus.None });
  // Set auth store hydrated state
  const store = useAuthStore.getState();
  store.setHydrated(hydrated);
}

describe("App", () => {
  afterEach(() => {
    vi.clearAllMocks();
    // Reset auth store
    useAuthStore.getState().setHydrated(false);
  });

  it("renders without crashing", () => {
    mockUseIsAuthenticated.mockReturnValue(false);
    mockUseMsal.mockReturnValue({ inProgress: InteractionStatus.None });
    expect(() => render(<App />)).not.toThrow();
  });

  it("shows LoadingState when auth store is not hydrated", async () => {
    mockUseIsAuthenticated.mockReturnValue(false);
    mockUseMsal.mockReturnValue({ inProgress: InteractionStatus.None });
    useAuthStore.getState().setHydrated(false);
    render(<App />);
    // LoadingState is rendered directly (not inside Suspense fallback)
    // Both Suspense fallback and hydrated=false render LoadingState
    // We verify neither LandingPage nor ChatPage is shown
    expect(screen.queryByTestId("landing-page")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chat-page")).not.toBeInTheDocument();
    // LoadingState spinner is present (role="status")
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows LandingPage when hydrated and not authenticated", async () => {
    setupAuth(false, true);
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId("landing-page")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("chat-page")).not.toBeInTheDocument();
  });

  it("shows ChatPage when hydrated and authenticated", async () => {
    setupAuth(true, true);
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId("chat-page")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("landing-page")).not.toBeInTheDocument();
  });

  it("shows LoadingState during MSAL transition", () => {
    mockUseIsAuthenticated.mockReturnValue(false);
    mockUseMsal.mockReturnValue({ inProgress: InteractionStatus.Startup });
    useAuthStore.getState().setHydrated(true);
    render(<App />);
    // AuthGuard catches the transition and shows LoadingState
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
