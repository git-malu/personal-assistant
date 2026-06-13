import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Button } from "@/components/ui/button";

describe("Button", () => {
  describe("apple-primary variant", () => {
    it("renders with correct classes", () => {
      render(<Button variant="apple-primary">Test</Button>);
      const btn = screen.getByRole("button", { name: "Test" });
      expect(btn.className).toContain("rounded-full");
      expect(btn.className).toContain("bg-primary");
      expect(btn.className).toContain("!h-auto");
      expect(btn.className).toContain("active:scale-95");
    });
  });

  describe("apple-secondary variant", () => {
    it("renders with correct classes", () => {
      render(<Button variant="apple-secondary">Test</Button>);
      const btn = screen.getByRole("button", { name: "Test" });
      expect(btn.className).toContain("border-primary");
      expect(btn.className).toContain("text-primary");
      expect(btn.className).toContain("rounded-full");
      expect(btn.className).toContain("!h-auto");
    });
  });

  describe("default variant", () => {
    it("renders without apple-specific classes", () => {
      render(<Button>Default</Button>);
      const btn = screen.getByRole("button", { name: "Default" });
      expect(btn.className).toContain("bg-primary");
      expect(btn.className).toContain("rounded-lg");
    });
  });

  describe("renders children", () => {
    it("renders text children", () => {
      render(<Button variant="apple-primary">Click Me</Button>);
      expect(screen.getByText("Click Me")).toBeInTheDocument();
    });

    it("renders HTML children", () => {
      render(
        <Button variant="apple-primary">
          <span data-testid="inner">Inner</span>
        </Button>
      );
      expect(screen.getByTestId("inner")).toBeInTheDocument();
    });
  });
});
