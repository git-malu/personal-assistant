import { LoginPlaceholder } from './LoginPlaceholder'
import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'
import { useChat } from '../hooks/useChat'

export function ChatContainer() {
  const { messages, sendMessage, isStreaming, error, clearError } = useChat()

  return (
    <div className="flex flex-col h-screen max-w-[480px] mx-auto bg-white dark:bg-gray-900">
      <LoginPlaceholder />
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-white">
          Personal Assistant
        </h1>
      </div>
      {/* Error banner */}
      {error && (
        <div className="flex-shrink-0 px-4 py-2 bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-sm flex justify-between items-center">
          <span>{error}</span>
          <button onClick={clearError} className="ml-2 font-bold text-lg leading-none">&times;</button>
        </div>
      )}
      <MessageList messages={messages} />
      <ChatInput onSend={sendMessage} disabled={isStreaming} />
    </div>
  )
}
