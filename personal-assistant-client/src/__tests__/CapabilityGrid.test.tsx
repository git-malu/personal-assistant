import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CapabilityGrid } from "@/components/landing/CapabilityGrid";
import { Calendar, Mail, NotebookPen, ListTodo } from "lucide-react";

describe("CapabilityGrid", () => {
  const mockCards = [
    { icon: Calendar, title: "日程管理", description: "管理日程" },
    { icon: Mail, title: "邮件处理", description: "处理邮件" },
    { icon: NotebookPen, title: "笔记记录", description: "记录笔记" },
    { icon: ListTodo, title: "任务管理", description: "管理任务" },
  ];

  it("renders headline", () => {
    render(<CapabilityGrid headline="核心能力" cards={mockCards} />);
    expect(screen.getByText("核心能力")).toBeInTheDocument();
  });

  it("maps cards array to CapabilityCard components correctly", () => {
    render(<CapabilityGrid headline="核心能力" cards={mockCards} />);
    // Each card title should be rendered
    expect(screen.getByText("日程管理")).toBeInTheDocument();
    expect(screen.getByText("邮件处理")).toBeInTheDocument();
    expect(screen.getByText("笔记记录")).toBeInTheDocument();
    expect(screen.getByText("任务管理")).toBeInTheDocument();
    // Each card description should be rendered
    expect(screen.getByText("管理日程")).toBeInTheDocument();
    expect(screen.getByText("处理邮件")).toBeInTheDocument();
    expect(screen.getByText("记录笔记")).toBeInTheDocument();
    expect(screen.getByText("管理任务")).toBeInTheDocument();
  });

  it("renders the correct number of card containers", () => {
    const { container } = render(
      <CapabilityGrid headline="核心能力" cards={mockCards} />
    );
    // All CapabilityCard divs have rounded-[18px]; count them
    const cards = container.querySelectorAll(".rounded-\\[18px\\]");
    expect(cards).toHaveLength(4);
  });

  it("has responsive grid classes", () => {
    const { container } = render(
      <CapabilityGrid headline="核心能力" cards={mockCards} />
    );
    const grid = container.querySelector(".grid");
    expect(grid).not.toBeNull();
    expect(grid?.className).toContain("grid");
    expect(grid?.className).toContain("grid-cols-1");
    expect(grid?.className).toContain("md:grid-cols-2");
    expect(grid?.className).toContain("lg:grid-cols-4");
  });

  it("handles empty cards array without crashing", () => {
    const { container } = render(
      <CapabilityGrid headline="Empty" cards={[]} />
    );
    expect(screen.getByText("Empty")).toBeInTheDocument();
    const cards = container.querySelectorAll(".rounded-\\[18px\\]");
    expect(cards).toHaveLength(0);
  });
});
