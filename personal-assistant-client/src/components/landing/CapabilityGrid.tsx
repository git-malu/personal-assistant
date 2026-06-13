import type { LucideIcon } from "lucide-react";
import { CapabilityCard } from "./CapabilityCard";

interface CapabilityGridProps {
  headline: string;
  cards: { icon: LucideIcon; title: string; description: string }[];
}

export function CapabilityGrid({ headline, cards }: CapabilityGridProps) {
  return (
    <section className="rounded-none bg-canvas-parchment py-[80px]">
      <div className="max-w-[980px] mx-auto">
        <h2 className="text-[40px] font-semibold leading-[1.1] text-center">
          {headline}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mt-12">
          {cards.map((card, index) => (
            <CapabilityCard
              key={index}
              icon={card.icon}
              title={card.title}
              description={card.description}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
