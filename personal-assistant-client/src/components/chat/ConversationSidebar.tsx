import {
  ThreadListItemMorePrimitive,
  ThreadListItemPrimitive,
  ThreadListPrimitive,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import {
  Archive,
  ArchiveRestore,
  Check,
  ChevronDown,
  ChevronRight,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Plus,
  RotateCw,
  Trash2,
  X,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useConversationListStore } from "@/stores/conversation-list-store";

interface ConversationSidebarProps {
  className?: string;
  onNavigate?: () => void;
  showCloseButton?: boolean;
}

function SidebarIconButton({
  label,
  children,
  className,
  ...props
}: React.ComponentProps<typeof Button> & { label: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            className={cn("size-10 md:size-7", className)}
            {...props}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function ConversationListItem({
  archived,
  onNavigate,
}: {
  archived: boolean;
  onNavigate?: () => void;
}) {
  const aui = useAui();
  const title = useAuiState((state) => state.threadListItem.title ?? "新对话");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const saveTitle = () => {
    const nextTitle = draft.trim();
    if (nextTitle && nextTitle !== title) {
      aui.threadListItem().rename(nextTitle);
    }
    setDraft(nextTitle || title);
    setEditing(false);
  };

  return (
    <ThreadListItemPrimitive.Root className="group flex min-h-11 items-center gap-1 rounded-lg px-1.5 data-[active=true]:bg-background md:min-h-10">
      {editing ? (
        <div className="flex min-w-0 flex-1 items-center gap-1">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") saveTitle();
              if (event.key === "Escape") setEditing(false);
            }}
            className="h-10 min-w-0 flex-1 rounded-lg border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/40 md:h-8"
            maxLength={200}
            aria-label="Conversation title"
            autoFocus
          />
          <SidebarIconButton label="Save title" onClick={saveTitle}>
            <Check />
          </SidebarIconButton>
          <SidebarIconButton label="Cancel rename" onClick={() => setEditing(false)}>
            <X />
          </SidebarIconButton>
        </div>
      ) : (
        <>
          <ThreadListItemPrimitive.Trigger
            onClick={(event) => {
              if (archived) {
                event.preventDefault();
                void aui.threadListItem().switchTo({ unarchive: false });
              }
              onNavigate?.();
            }}
            className="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/40 md:min-h-10"
          >
            <MessageSquare className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate">
              <ThreadListItemPrimitive.Title fallback="新对话" />
            </span>
          </ThreadListItemPrimitive.Trigger>
          <div className="flex shrink-0 items-center opacity-100 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
            <ThreadListItemMorePrimitive.Root>
              <ThreadListItemMorePrimitive.Trigger
                render={
                  <SidebarIconButton label="Conversation actions">
                    <MoreHorizontal />
                  </SidebarIconButton>
                }
              />
              <ThreadListItemMorePrimitive.Content
                side="bottom"
                align="end"
                className="z-50 min-w-44 rounded-lg border bg-popover p-1 text-sm text-popover-foreground"
              >
                <ThreadListItemMorePrimitive.Item
                  className="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2 outline-none focus:bg-accent md:min-h-8"
                  onClick={() => {
                    setDraft(title);
                    setEditing(true);
                  }}
                >
                  <Pencil className="size-4" />
                  Rename
                </ThreadListItemMorePrimitive.Item>
                <ThreadListItemMorePrimitive.Item
                  className="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2 outline-none focus:bg-accent md:min-h-8"
                  onClick={() => {
                    if (archived) aui.threadListItem().unarchive();
                    else aui.threadListItem().archive();
                  }}
                >
                  {archived ? (
                    <ArchiveRestore className="size-4" />
                  ) : (
                    <Archive className="size-4" />
                  )}
                  {archived ? "Restore" : "Archive"}
                </ThreadListItemMorePrimitive.Item>
                <ThreadListItemMorePrimitive.Item
                  className="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg px-2 text-destructive outline-none focus:bg-destructive/10 md:min-h-8"
                  onClick={() => setDeleteOpen(true)}
                >
                  <Trash2 className="size-4" />
                  Delete
                </ThreadListItemMorePrimitive.Item>
              </ThreadListItemMorePrimitive.Content>
            </ThreadListItemMorePrimitive.Root>
            <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
              <DialogContent className="rounded-lg">
                <DialogHeader>
                  <DialogTitle>Delete conversation?</DialogTitle>
                  <DialogDescription>
                    This permanently deletes the conversation and its message history.
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                  <Button
                    variant="destructive"
                    onClick={() => {
                      aui.threadListItem().delete();
                      setDeleteOpen(false);
                      onNavigate?.();
                    }}
                  >
                    Delete
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </>
      )}
    </ThreadListItemPrimitive.Root>
  );
}

function ConversationListSkeleton() {
  return (
    <div className="space-y-2 px-2" aria-label="Loading conversations">
      {["one", "two", "three", "four"].map((key) => (
        <div key={key} className="h-9 animate-pulse rounded-lg bg-muted" />
      ))}
    </div>
  );
}

export function ConversationSidebar({
  className,
  onNavigate,
  showCloseButton = false,
}: ConversationSidebarProps) {
  const aui = useAui();
  const isLoading = useAuiState((state) => state.threads.isLoading);
  const isLoadingMore = useAuiState((state) => state.threads.isLoadingMore);
  const hasMore = useAuiState((state) => state.threads.hasMore);
  const activeCount = useAuiState((state) => state.threads.threadIds.length);
  const archivedCount = useAuiState(
    (state) => state.threads.archivedThreadIds.length,
  );
  const error = useConversationListStore((state) => state.error);
  const [showArchived, setShowArchived] = useState(false);

  return (
    <ThreadListPrimitive.Root
      className={cn("flex h-full min-h-0 flex-col bg-muted/60", className)}
    >
      <div className="flex h-12 shrink-0 items-center justify-between border-b px-3">
        <span className="text-sm font-semibold">Conversations</span>
        <div className="flex items-center">
          <Tooltip>
            <TooltipTrigger
              render={
                <ThreadListPrimitive.New
                  onClick={onNavigate}
                  render={
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="size-11 md:size-7"
                      aria-label="New conversation"
                    />
                  }
                />
              }
            >
              <Plus />
            </TooltipTrigger>
            <TooltipContent>New conversation</TooltipContent>
          </Tooltip>
          {showCloseButton ? (
            <DialogClose
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="size-11"
                  aria-label="Close conversations"
                />
              }
            >
              <X />
            </DialogClose>
          ) : null}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
        {isLoading ? <ConversationListSkeleton /> : null}
        {!isLoading && error ? (
          <div className="px-2 py-6 text-center">
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button
              className="mt-3"
              variant="outline"
              size="sm"
              onClick={() => void aui.threads().reload()}
            >
              <RotateCw />
              Retry
            </Button>
          </div>
        ) : null}
        {!isLoading && !error ? (
          <>
            <div className="mb-2 px-2 text-xs font-semibold text-muted-foreground">
              Recent
            </div>
            <ThreadListPrimitive.Items>
              {() => <ConversationListItem archived={false} onNavigate={onNavigate} />}
            </ThreadListPrimitive.Items>
            {activeCount === 0 ? (
              <p className="px-2 py-5 text-sm text-muted-foreground">
                Start a new conversation.
              </p>
            ) : null}

            {archivedCount > 0 ? (
              <div className="mt-4 border-t pt-3">
                <Button
                  variant="ghost"
                  className="w-full justify-start text-xs text-muted-foreground"
                  onClick={() => setShowArchived((value) => !value)}
                >
                  {showArchived ? <ChevronDown /> : <ChevronRight />}
                  Archived
                  <span className="ml-auto">{archivedCount}</span>
                </Button>
                {showArchived ? (
                  <ThreadListPrimitive.Items archived>
                    {() => (
                      <ConversationListItem archived onNavigate={onNavigate} />
                    )}
                  </ThreadListPrimitive.Items>
                ) : null}
              </div>
            ) : null}

            {hasMore ? (
              <ThreadListPrimitive.LoadMore
                render={
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-3 w-full"
                    disabled={isLoadingMore}
                  />
                }
              >
                {isLoadingMore ? "Loading..." : "Load more"}
              </ThreadListPrimitive.LoadMore>
            ) : null}
          </>
        ) : null}
      </div>
    </ThreadListPrimitive.Root>
  );
}

export function ConversationDrawer() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            className="md:hidden"
            aria-label="Open conversations"
          />
        }
      >
        <Menu />
      </DialogTrigger>
      <DialogContent
        className="top-0 left-0 h-dvh w-72 max-w-[85vw] translate-x-0 translate-y-0 gap-0 rounded-none p-0"
        initialFocus={false}
        showCloseButton={false}
      >
        <DialogTitle className="sr-only">Conversations</DialogTitle>
        <ConversationSidebar
          onNavigate={() => setOpen(false)}
          showCloseButton
        />
      </DialogContent>
    </Dialog>
  );
}
