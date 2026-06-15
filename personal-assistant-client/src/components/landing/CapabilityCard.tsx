import type { LucideIcon } from "lucide-react";

interface CapabilityCardProps {
  icon: LucideIcon;
  title: string;
  description: string;
}

export function CapabilityCard({
  icon: Icon,
  title,
  description,
}: CapabilityCardProps) {
  return (
    <div className="rounded-[18px] border border-[#e0e0e0] bg-white p-6">
      <Icon className="h-6 w-6 text-primary" />
      <h3 className="text-[17px] font-semibold leading-[1.24] tracking-[-0.374px] mt-4">
        {title}
      </h3>
      <p className="text-[17px] font-normal leading-[1.47] tracking-[-0.374px] mt-2 text-[#333333]">
        {description}
      </p>
    </div>
  );
}
