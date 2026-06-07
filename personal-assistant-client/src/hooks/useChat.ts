import { useState, useRef, useCallback, useEffect } from 'react'
import type { Message, SSEEvent } from '../types/chat'

interface UseChatReturn {
  messages: Message[];
  sendMessage: (content: string) => void;
  isStreaming: boolean;
  error: string | null;
  clearError: () => void;
}

const MAX_RETRIES = 3

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef(false)
  const retryCountRef = useRef(0)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Cleanup EventSource on unmount
  useEffect(() => {
    return () => {
      abortRef.current = true
      eventSourceRef.current?.close()
    }
  }, [])

  const closeConnection = useCallback(() => {
    eventSourceRef.current?.close()
    eventSourceRef.current = null
  }, [])

  const clearError = useCallback(() => {
    setError(null)
    retryCountRef.current = 0
  }, [])

  const sendMessage = useCallback((content: string) => {
    const trimmed = content.trim()
    if (!trimmed) return

    // Abort any existing connection
    abortRef.current = true
    closeConnection()

    // Append user message
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: trimmed,
      timestamp: Date.now(),
    }

    // Create empty assistant message
    const assistantMessage: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isStreaming: true,
    }

    setMessages(prev => [...prev, userMessage, assistantMessage])
    setIsStreaming(true)
    setError(null)

    // Reset for new connection
    retryCountRef.current = 0
    abortRef.current = false

    const assistantId = assistantMessage.id
    const eventSource = new EventSource(
      `/api/chat/stream?q=${encodeURIComponent(trimmed)}`
    )
    eventSourceRef.current = eventSource

    eventSource.onopen = () => {
      // Connection established — browser handles the rest
    }

    eventSource.onmessage = (event) => {
      if (abortRef.current) return

      try {
        const data: SSEEvent = JSON.parse(event.data)

        if (data.token) {
          setMessages(prev =>
            prev.map(msg =>
              msg.id === assistantId
                ? { ...msg, content: msg.content + data.token }
                : msg
            )
          )
        }

        if (data.done) {
          retryCountRef.current = 0
          closeConnection()
          setIsStreaming(false)
          setMessages(prev =>
            prev.map(msg =>
              msg.id === assistantId
                ? { ...msg, isStreaming: false }
                : msg
            )
          )
        }
      } catch {
        // JSON parse error — ignore malformed events
      }
    }

    eventSource.onerror = () => {
      if (abortRef.current) return

      retryCountRef.current += 1

      if (retryCountRef.current >= MAX_RETRIES) {
        closeConnection()
        setError('连接失败，请稍后重试')

        // Preserve partial content + append interruption suffix
        setMessages(prev =>
          prev.map(msg =>
            msg.id === assistantId && msg.isStreaming
              ? { ...msg, content: msg.content + '[连接中断]', isStreaming: false }
              : msg
          )
        )
        setIsStreaming(false)
      }
    }
  }, [closeConnection])

  return {
    messages,
    sendMessage,
    isStreaming,
    error,
    clearError,
  }
}
