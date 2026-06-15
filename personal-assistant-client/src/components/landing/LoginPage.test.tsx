import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock @azure/msal-react — LoginPage calls useMsal()
const mockLoginRedirect = vi.fn();
const mockUseMsal = vi.fn().mockReturnValue({
  instance: { loginRedirect: mockLoginRedirect },
});

vi.mock("@azure/msal-react", () => ({
  useMsal: () => mockUseMsal(),
}));

// Mock @/lib/auth — LoginPage passes loginRequest to loginRedirect
vi.mock("@/lib/auth", () => ({
  loginRequest: { scopes: ["openid", "profile", "email", "User.Read"] },
}));

import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders back button with 返回 text", () => {
    render(<LoginPage onBack={vi.fn()} />);
    const backBtn = screen.getByRole("button", { name: /返回/ });
    expect(backBtn).toBeInTheDocument();
  });

  it("renders 3 providers (Microsoft, GitHub, WeChat)", () => {
    render(<LoginPage onBack={vi.fn()} />);
    expect(screen.getByText("Microsoft 账号")).toBeInTheDocument();
    expect(screen.getByText("GitHub 账号")).toBeInTheDocument();
    expect(screen.getByText("微信账号")).toBeInTheDocument();
  });

  it("renders the page heading", () => {
    render(<LoginPage onBack={vi.fn()} />);
    expect(
      screen.getByRole("heading", { name: /登录 Personal Assistant/ }),
    ).toBeInTheDocument();
  });

  it("renders the footer watermark", () => {
    render(<LoginPage onBack={vi.fn()} />);
    expect(screen.getByText("Personal Assistant")).toBeInTheDocument();
  });

  it("Microsoft row triggers login on click", async () => {
    const user = userEvent.setup();
    render(<LoginPage onBack={vi.fn()} />);

    const microsoftBtn = screen.getByRole("button", { name: /Microsoft 账号/ });
    await user.click(microsoftBtn);

    expect(mockLoginRedirect).toHaveBeenCalledTimes(1);
    expect(mockLoginRedirect).toHaveBeenCalledWith({
      scopes: ["openid", "profile", "email", "User.Read"],
    });
  });

  it("GitHub and WeChat show 即将支持 badge", () => {
    render(<LoginPage onBack={vi.fn()} />);
    const badges = screen.getAllByText("即将支持");
    expect(badges).toHaveLength(2);
  });

  it("GitHub row is disabled (not a button)", () => {
    render(<LoginPage onBack={vi.fn()} />);
    // GitHub row is a <div>, not a <button> — should not be clickable as a role=button
    expect(
      screen.queryByRole("button", { name: /GitHub 账号/ }),
    ).not.toBeInTheDocument();
    // It should still be rendered as text
    expect(screen.getByText("GitHub 账号")).toBeInTheDocument();
  });

  it("WeChat row is disabled (not a button)", () => {
    render(<LoginPage onBack={vi.fn()} />);
    expect(
      screen.queryByRole("button", { name: /微信账号/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("微信账号")).toBeInTheDocument();
  });

  it("back button calls onBack when clicked", async () => {
    const onBack = vi.fn();
    const user = userEvent.setup();
    render(<LoginPage onBack={onBack} />);

    const backBtn = screen.getByRole("button", { name: /返回/ });
    await user.click(backBtn);

    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
