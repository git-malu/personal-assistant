import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CapabilityCard } from "@/components/landing/CapabilityCard";
import { Calendar } from "lucide-react";

describe("CapabilityCard", () => {
  it("renders icon, title, and description", () => {
    render(
      <CapabilityCard
        icon={Calendar}
        title="日程管理"
        description="自然语言创建日程"
      />
    );
    expect(screen.getByText("日程管理")).toBeInTheDocument();
    expect(screen.getByText("自然语言创建日程")).toBeInTheDocument();
    // Icon renders as an SVG
    const svg = document.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it('has rounded-[18px] class', () => {
    const { container } = render(
      <CapabilityCard
        icon={Calendar}
        title="Test"
        description="Desc"
      />
    );
    const card = container.querySelector("div");
    expect(card?.className).toContain("rounded-[18px]");
  });

  it('has hairline border class border-[#e0e0e0]', () => {
    const { container } = render(
      <CapabilityCard
        icon={Calendar}
        title="Test"
        description="Desc"
      />
    );
    const card = container.querySelector("div");
    expect(card?.className).toContain("border-[#e0e0e0]");
  });

  it("has no shadow class", () => {
    const { container } = render(
      <CapabilityCard
        icon={Calendar}
        title="Test"
        description="Desc"
      />
    );
    const card = container.querySelector("div");
    expect(card?.className).not.toContain("shadow");
  });

  it('description color is text-[#333333]', () => {
    render(
      <CapabilityCard
        icon={Calendar}
        title="Test"
        description="Desc"
      />
    );
    const description = screen.getByText("Desc");
    expect(description.className).toContain("text-[#333333]");
  });

  it("has bg-white class", () => {
    const { container } = render(
      <CapabilityCard
        icon={Calendar}
        title="Test"
        description="Desc"
      />
    );
    const card = container.querySelector("div");
    expect(card?.className).toContain("bg-white");
  });
});
