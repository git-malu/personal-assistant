import { LoginPlaceholder } from './LoginPlaceholder'
import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'
import { useChat } from '../hooks/useChat'
import { Alert, AlertDescription } from '@/components/ui/alert'

export function ChatContainer() {
  const { messages, sendMessage, isStreaming, error, clearError } = useChat()

  return (
    <div className="flex flex-col h-screen max-w-[480px] mx-auto bg-background dark:bg-background">
      <LoginPlaceholder />
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-border">
        <h1 className="text-lg font-semibold text-foreground">
          Personal Assistant
        </h1>
      </div>
      {/* Error banner */}
      {error && (
        <Alert variant="destructive" className="flex-shrink-0 rounded-none border-0">
          <AlertDescription className="flex justify-between items-center">
            <span>{error}</span>
            <button onClick={clearError} className="ml-2 font-bold text-lg leading-none">&times;</button>
          </AlertDescription>
        </Alert>
      )}
      <MessageList messages={messages} />
      <ChatInput onSend={sendMessage} disabled={isStreaming} />
    </div>
  )
}
