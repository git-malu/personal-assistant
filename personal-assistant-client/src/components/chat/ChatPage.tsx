import { Thread } from "@/components/assistant-ui/thread";
import { TooltipProvider } from "@/components/ui/tooltip";
import { RuntimeProvider } from "@/components/RuntimeProvider";
import { LoginButton } from "@/components/LoginButton";
import {
  ConversationDrawer,
  ConversationSidebar,
} from "./ConversationSidebar";

function ChatPage() {
  return (
    <RuntimeProvider>
      <TooltipProvider>
        <div className="flex h-dvh bg-background">
          <ConversationSidebar className="hidden w-72 shrink-0 border-r md:flex" />
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex h-12 shrink-0 items-center justify-between gap-2 border-b px-3 md:px-4">
              <div className="flex min-w-0 items-center gap-2">
                <ConversationDrawer />
                <span className="truncate text-sm font-semibold">
                  Personal Assistant
                </span>
              </div>
              <div className="flex min-w-0 items-center gap-2">
                <LoginButton />
              </div>
            </div>
            <div className="min-h-0 flex-1">
              <Thread />
            </div>
          </div>
        </div>
      </TooltipProvider>
    </RuntimeProvider>
  );
}

export default ChatPage;
