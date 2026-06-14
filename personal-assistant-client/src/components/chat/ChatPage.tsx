import { Thread } from "@/components/assistant-ui/thread";
import { TooltipProvider } from "@/components/ui/tooltip";
import { RuntimeProvider } from "@/components/RuntimeProvider";
import { LoginButton } from "@/components/LoginButton";

function ChatPage() {
  return (
    <RuntimeProvider>
      <TooltipProvider>
        <div className="flex h-dvh flex-col bg-background">
          <nav className="dark flex h-[44px] w-full items-center justify-between bg-surface-black px-5">
            <a
              href="/"
              className="inline-flex h-full items-center text-[12px] font-normal leading-none tracking-[-0.12px] text-white/90 no-underline hover:text-white transition-colors"
              aria-label="Personal Assistant, 返回首页"
            >
              Personal Assistant
            </a>
            <LoginButton />
          </nav>
          <div className="flex-1 min-h-0">
            <Thread />
          </div>
        </div>
      </TooltipProvider>
    </RuntimeProvider>
  );
}

export default ChatPage;
