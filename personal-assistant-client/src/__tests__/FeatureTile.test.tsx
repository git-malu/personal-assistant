import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FeatureTile } from "@/components/landing/FeatureTile";

describe("FeatureTile", () => {
  it('renders "light" variant with correct background color class', () => {
    const { container } = render(
      <FeatureTile variant="light" headline="Test" description="Desc" />
    );
    const section = container.querySelector("section");
    expect(section?.className).toContain("bg-white");
  });

  it('renders "parchment" variant with correct background color class', () => {
    const { container } = render(
      <FeatureTile variant="parchment" headline="Test" description="Desc" />
    );
    const section = container.querySelector("section");
    expect(section?.className).toContain("bg-canvas-parchment");
  });

  it('renders "dark" variant with correct background color class', () => {
    const { container } = render(
      <FeatureTile variant="dark" headline="Test" description="Desc" />
    );
    const section = container.querySelector("section");
    expect(section?.className).toContain("bg-surface-tile-1");
    expect(section?.className).toContain("text-white");
  });

  it('renders "dark-2" variant with correct background color class', () => {
    const { container } = render(
      <FeatureTile variant="dark-2" headline="Test" description="Desc" />
    );
    const section = container.querySelector("section");
    expect(section?.className).toContain("bg-surface-tile-2");
    expect(section?.className).toContain("text-white");
  });

  it("has rounded-none class on the section", () => {
    const { container } = render(
      <FeatureTile variant="light" headline="Test" description="Desc" />
    );
    const section = container.querySelector("section");
    expect(section?.className).toContain("rounded-none");
  });

  it("renders headline and description correctly", () => {
    render(
      <FeatureTile variant="light" headline="My Headline" description="My Description" />
    );
    expect(screen.getByText("My Headline")).toBeInTheDocument();
    expect(screen.getByText("My Description")).toBeInTheDocument();
  });

  it("renders children slot correctly", () => {
    render(
      <FeatureTile variant="dark" headline="Test" description="Desc">
        <div data-testid="custom-child">Custom Content</div>
      </FeatureTile>
    );
    expect(screen.getByTestId("custom-child")).toBeInTheDocument();
    expect(screen.getByText("Custom Content")).toBeInTheDocument();
  });

  it("renders apple-primary Button when cta prop is provided", () => {
    const onClick = vi.fn();
    render(
      <FeatureTile
        variant="light"
        headline="Test"
        description="Desc"
        cta={{ label: "Learn More", onClick }}
      />
    );
    const button = screen.getByRole("button", { name: "Learn More" });
    expect(button).toBeInTheDocument();
    // apple-primary variant adds rounded-full class
    expect(button.className).toContain("rounded-full");
  });

  it("calls cta onClick when button is clicked", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(
      <FeatureTile
        variant="light"
        headline="Test"
        description="Desc"
        cta={{ label: "Learn More", onClick }}
      />
    );
    await user.click(screen.getByRole("button", { name: "Learn More" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("does not render a button when cta is undefined", () => {
    render(
      <FeatureTile variant="light" headline="Test" description="Desc" />
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
