import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Mock CPU-heavy modules to keep App smoke tests lightweight.
 * - RuntimeProvider → simple passthrough (tested separately)
 * - Thread → empty placeholder (huge dependency tree)
 */
vi.mock("@/components/RuntimeProvider", () => ({
  RuntimeProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("@/components/assistant-ui/thread", () => ({
  Thread: () => <div data-testid="thread">Thread</div>,
}));

// Mock @azure/msal-react hooks
const mockUseIsAuthenticated = vi.fn();

vi.mock("@azure/msal-react", () => ({
  useIsAuthenticated: () => mockUseIsAuthenticated(),
  useMsal: () => ({
    instance: {
      loginPopup: vi.fn(),
      logoutPopup: vi.fn(),
    },
  }),
}));

import App from "./App";

describe("App", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crashing", () => {
    mockUseIsAuthenticated.mockReturnValue(false);
    expect(() => render(<App />)).not.toThrow();
  });

  it("renders the auth header bar with login prompt when not authenticated", () => {
    mockUseIsAuthenticated.mockReturnValue(false);
    render(<App />);
    // Should show the "请登录以开始对话" status text
    expect(screen.getByText("请登录以开始对话")).toBeInTheDocument();
  });

  it("renders the auth header bar with authenticated status when logged in", () => {
    mockUseIsAuthenticated.mockReturnValue(true);
    render(<App />);
    // Should show the "已登录" status text
    expect(screen.getByText("已登录")).toBeInTheDocument();
  });

  it("renders LoginButton in the auth header bar", () => {
    mockUseIsAuthenticated.mockReturnValue(false);
    render(<App />);
    // LoginButton renders differently depending on env; in test mode
    // VITE_ENTRA_CLIENT_ID is typically not set, so it shows dev mode text
    expect(
      screen.getByText(/Dev Mode — Proxy auth enabled/),
    ).toBeInTheDocument();
  });

  it("renders the Thread component area", () => {
    mockUseIsAuthenticated.mockReturnValue(false);
    render(<App />);
    expect(screen.getByTestId("thread")).toBeInTheDocument();
  });
});
