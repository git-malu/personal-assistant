import { Button } from "@/components/ui/button";

interface GlobalNavProps {
  onLogin?: () => void;
}

export function GlobalNav({ onLogin }: GlobalNavProps) {
  const isDev = !import.meta.env.VITE_ENTRA_CLIENT_ID;

  return (
    <nav className="sticky top-0 z-50 flex h-[44px] w-full items-center justify-between bg-surface-black px-5">
      <span className="text-[12px] font-normal text-white/90 hidden lg:inline">
        Personal Assistant
      </span>
      <div className="ml-auto">
        {isDev ? (
          <span className="text-[12px] text-white/60">Dev Mode</span>
        ) : (
          <Button variant="ghost" size="sm" onClick={onLogin}
            className="text-[12px] text-white hover:text-white/80">
            登录
          </Button>
        )}
      </div>
    </nav>
  );
}
