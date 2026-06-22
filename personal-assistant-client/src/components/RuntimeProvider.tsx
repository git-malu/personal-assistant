import { type ReactNode, useMemo } from "react";
import {
  useLocalRuntime,
  AssistantRuntimeProvider,
  useAuiState,
  useRemoteThreadListRuntime,
} from "@assistant-ui/react";
import { createChatAdapter } from "@/lib/chat-adapter";
import {
  conversationListAdapter,
  createHistoryAdapter,
} from "@/lib/conversations/adapters";
import { RuntimeStatusProvider } from "@/components/chat/RuntimeStatus";

export function RuntimeProvider({ children }: { children: ReactNode }) {
  const runtime = useRemoteThreadListRuntime({
    adapter: conversationListAdapter,
    runtimeHook: function ConversationRuntime() {
      const conversationId = useAuiState(
        (state) => state.threadListItem.remoteId,
      );
      const adapter = useMemo(
        () => createChatAdapter(() => conversationId),
        [conversationId],
      );
      const history = useMemo(
        () => createHistoryAdapter(conversationId),
        [conversationId],
      );
      return useLocalRuntime(adapter, { adapters: { history } });
    },
  });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <RuntimeStatusProvider>{children}</RuntimeStatusProvider>
    </AssistantRuntimeProvider>
  );
}
