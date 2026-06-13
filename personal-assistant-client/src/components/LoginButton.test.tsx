import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock @azure/msal-react hooks — must always return valid shapes because
// LoginButton calls useMsal() and useIsAuthenticated() before the dev-mode
// early-return guard (React hooks must be called unconditionally).
const mockUseMsal = vi.fn().mockReturnValue({
  instance: {
    loginRedirect: vi.fn(),
    logoutRedirect: vi.fn(),
  },
  accounts: [],
});
const mockUseIsAuthenticated = vi.fn().mockReturnValue(false);

vi.mock("@azure/msal-react", () => ({
  useMsal: () => mockUseMsal(),
  useIsAuthenticated: () => mockUseIsAuthenticated(),
}));

import { LoginButton } from "./LoginButton";

describe("LoginButton", () => {
  afterEach(() => {
    vi.clearAllMocks();
    // Clear env stubs
    vi.unstubAllEnvs();
  });

  describe("in dev mode (no VITE_ENTRA_CLIENT_ID)", () => {
    it('renders "Dev Mode — Proxy auth enabled" text', () => {
      // Ensure VITE_ENTRA_CLIENT_ID is not defined
      vi.stubEnv("VITE_ENTRA_CLIENT_ID", undefined as unknown as string);
      render(<LoginButton />);
      expect(
        screen.getByText(/Dev Mode — Proxy auth enabled/),
      ).toBeInTheDocument();
    });

    it("does not render login or logout buttons in dev mode", () => {
      vi.stubEnv("VITE_ENTRA_CLIENT_ID", undefined as unknown as string);
      render(<LoginButton />);
      expect(
        screen.queryByRole("button", { name: /sign in/i }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /logout/i }),
      ).not.toBeInTheDocument();
    });
  });

  describe("when VITE_ENTRA_CLIENT_ID is set", () => {
    beforeEach(() => {
      vi.stubEnv("VITE_ENTRA_CLIENT_ID", "test-client-id");
    });

    it("renders 'Sign in with Microsoft' button when not authenticated", () => {
      mockUseMsal.mockReturnValue({
        instance: {
          loginRedirect: vi.fn(),
          logoutRedirect: vi.fn(),
        },
        accounts: [],
      });
      mockUseIsAuthenticated.mockReturnValue(false);

      render(<LoginButton />);

      expect(
        screen.getByRole("button", { name: /sign in with microsoft/i }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /logout/i }),
      ).not.toBeInTheDocument();
    });

    it("renders 'Logout' button when authenticated", () => {
      mockUseMsal.mockReturnValue({
        instance: {
          loginRedirect: vi.fn(),
          logoutRedirect: vi.fn(),
        },
        accounts: [{ name: "Test User", username: "test@example.com" }],
      });
      mockUseIsAuthenticated.mockReturnValue(true);

      render(<LoginButton />);

      expect(
        screen.getByRole("button", { name: /logout/i }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /sign in/i }),
      ).not.toBeInTheDocument();
    });

    it("calls instance.loginRedirect when Sign in button is clicked", async () => {
      const loginRedirect = vi.fn().mockResolvedValue(undefined);
      mockUseMsal.mockReturnValue({
        instance: { loginRedirect, logoutRedirect: vi.fn() },
        accounts: [],
      });
      mockUseIsAuthenticated.mockReturnValue(false);

      const user = userEvent.setup();
      render(<LoginButton />);

      await user.click(screen.getByRole("button", { name: /sign in with microsoft/i }));
      expect(loginRedirect).toHaveBeenCalledTimes(1);
    });

    it("calls instance.logoutRedirect when Logout button is clicked", async () => {
      const logoutRedirect = vi.fn().mockResolvedValue(undefined);
      mockUseMsal.mockReturnValue({
        instance: { loginRedirect: vi.fn(), logoutRedirect },
        accounts: [{ name: "Test User", username: "test@example.com" }],
      });
      mockUseIsAuthenticated.mockReturnValue(true);

      const user = userEvent.setup();
      render(<LoginButton />);

      await user.click(screen.getByRole("button", { name: /logout/i }));
      expect(logoutRedirect).toHaveBeenCalledTimes(1);
    });

    it("handles loginRedirect rejection gracefully (no crash)", async () => {
      const consoleSpy = vi
        .spyOn(console, "error")
        .mockImplementation(() => {});
      const loginRedirect = vi.fn().mockRejectedValue(new Error("redirect failed"));
      mockUseMsal.mockReturnValue({
        instance: { loginRedirect, logoutRedirect: vi.fn() },
        accounts: [],
      });
      mockUseIsAuthenticated.mockReturnValue(false);

      const user = userEvent.setup();
      render(<LoginButton />);

      await user.click(screen.getByRole("button", { name: /sign in with microsoft/i }));
      // Should not throw — error is caught and logged
      expect(loginRedirect).toHaveBeenCalledTimes(1);
      expect(consoleSpy).toHaveBeenCalledWith(
        "Login failed:",
        expect.any(Error),
      );

      consoleSpy.mockRestore();
    });
  });
});
