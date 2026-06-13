import { Button } from "@/components/ui/button";
import { FeatureTile } from "./FeatureTile";

interface ClosingCTAProps {
  cta: { label: string; onClick: () => void };
}

export function ClosingCTA({ cta }: ClosingCTAProps) {
  return (
    <FeatureTile
      variant="dark-2"
      headline="准备好了吗？"
      description="立即开始使用 Personal Assistant，让 AI 帮您管理日常事务。"
      cta={undefined}
    >
      <Button variant="apple-primary" onClick={cta.onClick} className="text-[18px]">
        {cta.label}
      </Button>
    </FeatureTile>
  );
}
