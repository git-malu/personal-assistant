import { type ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface FeatureTileProps {
  variant: "light" | "parchment" | "dark" | "dark-2";
  headline: string;
  description: string;
  cta?: { label: string; onClick: () => void };
  children?: ReactNode;
}

const surfaceMap = {
  light: "bg-white text-[#1d1d1f]",
  parchment: "bg-canvas-parchment text-[#1d1d1f]",
  dark: "bg-surface-tile-1 text-white",
  "dark-2": "bg-surface-tile-2 text-white",
};

export function FeatureTile({
  variant,
  headline,
  description,
  cta,
  children,
}: FeatureTileProps) {
  return (
    <section className={`rounded-none py-[80px] ${surfaceMap[variant]}`}>
      <div className="max-w-[980px] mx-auto">
        <h2 className="text-[40px] font-semibold leading-[1.1] tracking-[0]">
          {headline}
        </h2>
        <p className="text-[17px] font-normal leading-[1.47] tracking-[-0.374px] mt-6">
          {description}
        </p>
        {cta && (
          <div className="mt-8">
            <Button variant="apple-primary" onClick={cta.onClick}>
              {cta.label}
            </Button>
          </div>
        )}
        {children && <div className="mt-12">{children}</div>}
      </div>
    </section>
  );
}
