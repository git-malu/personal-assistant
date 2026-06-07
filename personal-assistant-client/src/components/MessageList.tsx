import { useEffect, useRef } from 'react'
import type { Message } from '../types/chat'
import { MessageBubble } from './MessageBubble'

interface MessageListProps {
  messages: Message[];
}

export function MessageList({ messages }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const isNearBottomRef = useRef(true)

  // Track whether user is near the bottom
  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const threshold = 100
    isNearBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < threshold
  }

  // Auto-scroll to bottom when messages change, but only if user was near bottom
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    if (isNearBottomRef.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages])

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto px-4 py-4"
      onScroll={handleScroll}
    >
      {messages.map(msg => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
    </div>
  )
}
