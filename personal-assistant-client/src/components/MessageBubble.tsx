import type { Message } from '../types/chat'
import { StreamingText } from './StreamingText'

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex flex-col mb-4 ${isUser ? 'items-end' : 'items-start'}`}>
      <div
        className={`max-w-[75%] px-3 py-2 rounded-2xl break-words ${
          isUser
            ? 'self-end bg-primary text-primary-foreground rounded-bl-lg'
            : 'self-start bg-muted text-foreground dark:text-foreground rounded-br-lg'
        }`}
      >
        <StreamingText
          text={message.content}
          isStreaming={message.isStreaming ?? false}
        />
      </div>
    </div>
  )
}
