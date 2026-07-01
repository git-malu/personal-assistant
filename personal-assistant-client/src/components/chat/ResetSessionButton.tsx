import { useAui, useAuiState } from "@assistant-ui/react";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { resetSessionId } from "@/lib/chat-adapter";
import { useState } from "react";

export function ResetSessionButton() {
  const aui = useAui();
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const [open, setOpen] = useState(false);

  const handleConfirm = async () => {
    try {
      // 1. 停止当前 streaming（cancelRun 同步，幂等）
      aui.thread().cancelRun();

      // 2. 清空 thread 消息，界面回到 welcome 状态
      aui.thread().reset();

      // 3. 清空输入框（异步操作）
      await aui.composer().reset();

      // 4. 切换并初始化新的 remote thread，保持与侧边栏“新对话”一致。
      const assistantRuntime = aui.threads().__internal_getAssistantRuntime?.();
      if (assistantRuntime) {
        await assistantRuntime.threads.switchToNewThread();
        await assistantRuntime.threads.mainItem.initialize();
      } else {
        const threads = aui.threads();
        await threads.switchToNewThread();
        await threads.item("main").initialize();
      }

      // 5. 最后清除 legacy localStorage session hint
      //    放在 UI 重置之后：若 UI 重置失败，session ID 保持不变，用户可重试
      resetSessionId();
    } catch (e) {
      console.error("Failed during session reset:", e);
    } finally {
      setOpen(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger
          render={
            <DialogTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  disabled={isRunning}
                  aria-label="新对话"
                />
              }
            />
          }
        >
          <RotateCcw className="size-4" />
        </TooltipTrigger>
        <TooltipContent>
          <p>新对话</p>
        </TooltipContent>
      </Tooltip>

      <DialogContent>
        <DialogHeader>
          <DialogTitle>新对话</DialogTitle>
          <DialogDescription>
            开始全新对话，当前会话记录将被清除。此操作无法撤销。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>
            取消
          </DialogClose>
          <Button
            variant="apple-secondary"
            onClick={handleConfirm}
          >
            确认
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
