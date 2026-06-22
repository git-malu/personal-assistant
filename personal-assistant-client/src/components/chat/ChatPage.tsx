import { Thread } from "@/components/assistant-ui/thread";
import { TooltipProvider } from "@/components/ui/tooltip";
import { RuntimeProvider } from "@/components/RuntimeProvider";
import { ConversationSidebar } from "./ConversationSidebar";
import { Menu, MoreHorizontal } from "lucide-react";
import { useState } from "react";
import { useAuiState } from "@assistant-ui/react";

function ChatShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const title = useAuiState(
    (state) => state.threadListItem.title ?? "新对话",
  );

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <ConversationSidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="grid h-16 shrink-0 grid-cols-[1fr_auto_1fr] items-center border-b bg-background/85 px-3 backdrop-blur-xl">
          <button
            className="grid size-10 place-items-center rounded-full hover:bg-muted md:invisible"
            onClick={() => setSidebarOpen(true)}
            aria-label="打开侧边栏"
          >
            <Menu className="size-4" />
          </button>
          <div className="text-center">
            <div className="max-w-[42vw] truncate text-sm font-semibold">
              {title}
            </div>
            <div className="text-[11px] text-muted-foreground">Conversation</div>
          </div>
          <button
            className="grid size-10 place-items-center justify-self-end rounded-full hover:bg-muted"
            aria-label="更多操作"
          >
            <MoreHorizontal className="size-4" />
          </button>
        </header>
        <main className="min-h-0 flex-1">
          <Thread />
        </main>
      </div>
    </div>
  );
}

function ChatPage() {
  return (
    <RuntimeProvider>
      <TooltipProvider>
        <ChatShell />
      </TooltipProvider>
    </RuntimeProvider>
  );
}

export default ChatPage;
