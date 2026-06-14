import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ChatPage from "./ChatPage";

vi.mock("@/components/RuntimeProvider", () => ({
  RuntimeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/assistant-ui/thread", () => ({
  Thread: () => <div data-testid="thread">Thread</div>,
}));
vi.mock("@/components/ui/tooltip", () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/LoginButton", () => ({
  LoginButton: () => <div data-testid="login-button">LoginButton</div>,
}));

describe("ChatPage", () => {
  describe("CP-01: Component renders without crashing", () => {
    it("render(<ChatPage />) does not throw", () => {
      expect(() => render(<ChatPage />)).not.toThrow();
    });
  });

  describe("CP-02: Header is <nav> with correct classes", () => {
    it('getByRole("navigation") exists and has bg-surface-black AND dark classes', () => {
      render(<ChatPage />);
      const nav = screen.getByRole("navigation");
      expect(nav).toBeInTheDocument();
      expect(nav.className).toMatch(/\bbg-surface-black\b/);
      expect(nav.className).toMatch(/\bdark\b/);
    });
  });

  describe("CP-03: 'Personal Assistant' is a link", () => {
    it('getByRole("link", { name: /Personal Assistant/ }) exists', () => {
      render(<ChatPage />);
      const link = screen.getByRole("link", { name: /Personal Assistant/ });
      expect(link).toBeInTheDocument();
    });
  });

  describe('CP-04: Link has href="/"', () => {
    it('getByRole("link").getAttribute("href") equals "/"', () => {
      render(<ChatPage />);
      const link = screen.getByRole("link", { name: /Personal Assistant/ });
      expect(link.getAttribute("href")).toBe("/");
    });
  });

  describe("CP-05: Link has aria-label for home navigation", () => {
    it('getByRole("link").getAttribute("aria-label") includes "返回首页"', () => {
      render(<ChatPage />);
      const link = screen.getByRole("link", { name: /Personal Assistant/ });
      expect(link.getAttribute("aria-label")).toContain("返回首页");
    });
  });

  describe("CP-06: Link has no-underline class", () => {
    it("Element's className includes no-underline", () => {
      render(<ChatPage />);
      const link = screen.getByRole("link", { name: /Personal Assistant/ });
      expect(link.className).toMatch(/\bno-underline\b/);
    });
  });

  describe("CP-07: LoginButton rendered inside <nav>", () => {
    it("getByTestId('login-button') is a descendant of <nav>", () => {
      render(<ChatPage />);
      const nav = screen.getByRole("navigation");
      const loginBtn = screen.getByTestId("login-button");
      expect(nav.contains(loginBtn)).toBe(true);
    });
  });

  describe("CP-08: Nav has fixed height 44px", () => {
    it("Nav element's className includes h-[44px]", () => {
      render(<ChatPage />);
      const nav = screen.getByRole("navigation");
      expect(nav.className).toMatch(/h-\[44px\]/);
    });
  });

  describe("CP-09: Thread component is rendered", () => {
    it('getByTestId("thread") exists', () => {
      render(<ChatPage />);
      const thread = screen.getByTestId("thread");
      expect(thread).toBeInTheDocument();
    });
  });
});
