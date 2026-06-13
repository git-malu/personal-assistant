import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LandingHero } from "@/components/landing/LandingHero";

describe("LandingHero", () => {
  const primaryCta = { label: "开始对话", onClick: vi.fn() };
  const secondaryCta = { label: "了解更多", onClick: vi.fn() };

  it("renders headline and tagline", () => {
    render(
      <LandingHero
        headline="Personal Assistant"
        tagline="您的 AI 助手"
        primaryCta={primaryCta}
      />
    );
    expect(screen.getByText("Personal Assistant")).toBeInTheDocument();
    expect(screen.getByText("您的 AI 助手")).toBeInTheDocument();
  });

  it('headline has text-[56px] class', () => {
    render(
      <LandingHero
        headline="Test"
        tagline="Tagline"
        primaryCta={primaryCta}
      />
    );
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.className).toContain("text-[56px]");
  });

  it("renders dual CTA buttons (primary + secondary) when both are provided", () => {
    render(
      <LandingHero
        headline="Test"
        tagline="Tagline"
        primaryCta={primaryCta}
        secondaryCta={secondaryCta}
      />
    );
    expect(screen.getByRole("button", { name: "开始对话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "了解更多" })).toBeInTheDocument();
  });

  it("renders only primary CTA when secondaryCta is undefined", () => {
    render(
      <LandingHero
        headline="Test"
        tagline="Tagline"
        primaryCta={primaryCta}
      />
    );
    expect(screen.getByRole("button", { name: "开始对话" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /了解更多/ })).not.toBeInTheDocument();
  });

  it("primary CTA button has apple-primary variant classes", () => {
    render(
      <LandingHero
        headline="Test"
        tagline="Tagline"
        primaryCta={primaryCta}
      />
    );
    const btn = screen.getByRole("button", { name: "开始对话" });
    expect(btn.className).toContain("rounded-full");
    expect(btn.className).toContain("bg-primary");
  });

  it("secondary CTA button has apple-secondary variant classes", () => {
    render(
      <LandingHero
        headline="Test"
        tagline="Tagline"
        primaryCta={primaryCta}
        secondaryCta={secondaryCta}
      />
    );
    const btn = screen.getByRole("button", { name: "了解更多" });
    expect(btn.className).toContain("rounded-full");
    expect(btn.className).toContain("border-primary");
    expect(btn.className).toContain("text-primary");
  });

  it("calls primaryCta.onClick when primary button is clicked", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <LandingHero
        headline="Test"
        tagline="Tagline"
        primaryCta={{ label: "开始对话", onClick }}
      />
    );
    await user.click(screen.getByRole("button", { name: "开始对话" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("calls secondaryCta.onClick when secondary button is clicked", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <LandingHero
        headline="Test"
        tagline="Tagline"
        primaryCta={primaryCta}
        secondaryCta={{ label: "了解更多", onClick }}
      />
    );
    await user.click(screen.getByRole("button", { name: "了解更多" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
