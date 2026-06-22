import { useState } from "react";
import {
  ThreadListItemPrimitive,
  ThreadListPrimitive,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import {
  Archive,
  Check,
  MoreHorizontal,
  PanelLeftClose,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { RuntimeStatus } from "./RuntimeStatus";

function ConversationItem() {
  const aui = useAui();
  const title = useAuiState((state) => state.threadListItem.title);
  const remoteId = useAuiState((state) => state.threadListItem.remoteId);
  const status = useAuiState((state) => state.threadListItem.status);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title ?? "新对话");

  const save = async () => {
    const next = draft.trim();
    if (next) await aui.threadListItem().rename(next);
    setEditing(false);
  };

  return (
    <ThreadListItemPrimitive.Root className="group relative mx-2 my-0.5 rounded-xl data-[active=true]:bg-background hover:bg-background/70">
      {editing ? (
        <div className="flex items-center gap-1 p-2">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void save();
              if (event.key === "Escape") setEditing(false);
            }}
            className="min-w-0 flex-1 rounded-lg border bg-background px-2 py-1.5 text-sm outline-none focus:border-primary"
            autoFocus
            aria-label="对话标题"
          />
          <button onClick={() => void save()} aria-label="保存标题">
            <Check className="size-4" />
          </button>
          <button onClick={() => setEditing(false)} aria-label="取消重命名">
            <X className="size-4" />
          </button>
        </div>
      ) : (
        <>
          <ThreadListItemPrimitive.Trigger className="block w-full px-3 py-2.5 pr-9 text-left">
            <span className="block truncate text-sm font-medium">
              {title ?? "新对话"}
            </span>
            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
              {remoteId ? "点击恢复这段对话" : "尚未保存"}
            </span>
          </ThreadListItemPrimitive.Trigger>
          <div className="absolute right-2 top-1/2 flex -translate-y-1/2 opacity-0 group-hover:opacity-100 group-data-[active=true]:opacity-100">
            <button
              className="rounded-full p-1.5 hover:bg-muted"
              onClick={() => {
                setDraft(title ?? "新对话");
                setEditing(true);
              }}
              aria-label="重命名对话"
            >
              <Pencil className="size-3.5" />
            </button>
            {status === "archived" ? (
              <ThreadListItemPrimitive.Unarchive
                className="rounded-full p-1.5 hover:bg-muted"
                aria-label="恢复对话"
              >
                <Archive className="size-3.5" />
              </ThreadListItemPrimitive.Unarchive>
            ) : (
              <ThreadListItemPrimitive.Archive
                className="rounded-full p-1.5 hover:bg-muted"
                aria-label="归档对话"
              >
                <Archive className="size-3.5" />
              </ThreadListItemPrimitive.Archive>
            )}
            <ThreadListItemPrimitive.Delete
              className="rounded-full p-1.5 text-destructive hover:bg-destructive/10"
              aria-label="删除对话"
            >
              <Trash2 className="size-3.5" />
            </ThreadListItemPrimitive.Delete>
          </div>
        </>
      )}
    </ThreadListItemPrimitive.Root>
  );
}

export function ConversationSidebar({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const aui = useAui();
  const [creating, setCreating] = useState(false);

  const createNewConversation = async () => {
    if (creating) return;
    setCreating(true);
    try {
      await aui.threads().switchToNewThread();
      await aui.threadListItem().initialize();
    } finally {
      setCreating(false);
      onClose();
    }
  };

  return (
    <>
      <button
        aria-label="关闭侧边栏"
        className={`fixed inset-0 z-30 bg-black/20 md:hidden ${open ? "block" : "hidden"}`}
        onClick={onClose}
      />
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[292px] flex-col border-r bg-canvas-parchment transition-transform md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-16 items-center justify-between px-4">
          <div className="flex items-center gap-2.5 font-semibold">
            <span className="grid size-8 place-items-center rounded-lg bg-foreground text-xs text-background">
              PA
            </span>
            Personal Assistant
          </div>
          <button
            className="grid size-10 place-items-center rounded-full hover:bg-black/5"
            onClick={onClose}
            aria-label="收起侧边栏"
          >
            <PanelLeftClose className="size-4" />
          </button>
        </div>

        <button
          className="mx-3 flex h-11 items-center justify-center gap-2 rounded-full bg-primary font-semibold text-primary-foreground active:scale-[0.98] disabled:opacity-60"
          onClick={() => void createNewConversation()}
          disabled={creating}
        >
          <Plus className="size-4" />
          {creating ? "创建中…" : "新对话"}
        </button>

        <div className="px-5 pb-2 pt-4 text-xs font-semibold text-muted-foreground">
          最近对话
        </div>
        <ThreadListPrimitive.Root className="min-h-0 flex-1 overflow-y-auto">
          <ThreadListPrimitive.Items
            components={{ ThreadListItem: ConversationItem }}
          />
          <ThreadListPrimitive.LoadMore className="mx-auto my-2 block rounded-full px-3 py-1.5 text-xs text-muted-foreground hover:bg-background">
            加载更多
          </ThreadListPrimitive.LoadMore>
          <details className="mx-3 mt-3">
            <summary className="cursor-pointer text-xs text-muted-foreground">
              已归档
            </summary>
            <div className="mt-2">
              <ThreadListPrimitive.Items
                archived
                components={{ ThreadListItem: ConversationItem }}
              />
            </div>
          </details>
        </ThreadListPrimitive.Root>

        <div className="m-3 flex items-center gap-3 border-t pt-3">
          <span className="grid size-9 place-items-center rounded-full bg-foreground text-xs font-semibold text-background">
            WY
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold">Windy Yang</div>
            <RuntimeStatus />
          </div>
          <MoreHorizontal className="size-4 text-muted-foreground" />
        </div>
      </aside>
    </>
  );
}
