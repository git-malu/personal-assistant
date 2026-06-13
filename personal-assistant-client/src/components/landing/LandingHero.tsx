import { Button } from "@/components/ui/button";

interface LandingHeroProps {
  headline: string;
  tagline: string;
  primaryCta: { label: string; onClick: () => void };
  secondaryCta?: { label: string; onClick: () => void };
}

export function LandingHero({
  headline,
  tagline,
  primaryCta,
  secondaryCta,
}: LandingHeroProps) {
  return (
    <section className="rounded-none min-h-[85vh] bg-white">
      <div className="max-w-[980px] mx-auto py-[80px]">
        <h1 className="text-[56px] font-semibold leading-[1.07] tracking-[-0.28px]">
          {headline}
        </h1>
        <p className="text-[28px] font-normal leading-[1.14] tracking-[0.196px] mt-6">
          {tagline}
        </p>
        <div className="mt-12 flex gap-4">
          <Button variant="apple-primary" onClick={primaryCta.onClick}>
            {primaryCta.label}
          </Button>
          {secondaryCta && (
            <Button variant="apple-secondary" onClick={secondaryCta.onClick}>
              {secondaryCta.label}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
