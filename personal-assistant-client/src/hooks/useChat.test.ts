import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useChat } from './useChat'

// Mutable holder so we can inspect the EventSource instance in tests
let lastEventSourceInstance: MockEventSource | null = null

class MockEventSource {
  url: string
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null

  constructor(_url: string) {
    this.url = _url
    lastEventSourceInstance = this
  }

  close() {
    lastEventSourceInstance = null
  }
}

// Replace the global EventSource with our mock
vi.stubGlobal('EventSource', MockEventSource)

describe('useChat', () => {
  beforeEach(() => {
    lastEventSourceInstance = null
  })

  afterEach(() => {
    lastEventSourceInstance = null
  })

  // ------------------------------------------------------------------
  // 1. Message sending
  // ------------------------------------------------------------------
  describe('sendMessage', () => {
    it('should append user message and empty assistant placeholder', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Hello')
      })

      const msgs = result.current.messages
      expect(msgs).toHaveLength(2)
      expect(msgs[0].role).toBe('user')
      expect(msgs[0].content).toBe('Hello')
      expect(msgs[1].role).toBe('assistant')
      expect(msgs[1].content).toBe('')
      expect(msgs[1].isStreaming).toBe(true)
    })

    it('should set isStreaming to true when sending', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Hello')
      })

      expect(result.current.isStreaming).toBe(true)
    })

    it('should clear any previous error when sending', () => {
      const { result } = renderHook(() => useChat())

      // Simulate 3 errors to set the error state
      act(() => {
        result.current.sendMessage('msg')
      })
      const es = lastEventSourceInstance!
      for (let i = 0; i < 3; i++) {
        act(() => { es.onerror?.() })
      }

      expect(result.current.error).not.toBeNull()

      // Now send a new message — error should be cleared
      act(() => {
        result.current.sendMessage('new msg')
      })

      expect(result.current.error).toBeNull()
    })

    it('should ignore empty or whitespace content', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('   ')
      })

      expect(result.current.messages).toHaveLength(0)
      expect(result.current.isStreaming).toBe(false)
    })
  })

  // ------------------------------------------------------------------
  // 2. Token receiving (onmessage)
  // ------------------------------------------------------------------
  describe('token receiving', () => {
    it('should append tokens to the assistant message', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Hello')
      })

      const es = lastEventSourceInstance!
      const assistantId = result.current.messages[1].id

      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"token":"你"}' }))
      })

      let assistant = result.current.messages.find(m => m.id === assistantId)
      expect(assistant?.content).toBe('你')

      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"token":"好"}' }))
      })

      assistant = result.current.messages.find(m => m.id === assistantId)
      expect(assistant?.content).toBe('你好')
    })

    it('should keep user message unchanged during streaming', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Hello')
      })

      const es = lastEventSourceInstance!

      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"token":"Hi"}' }))
      })

      const userMsg = result.current.messages[0]
      expect(userMsg.content).toBe('Hello')
      expect(userMsg.role).toBe('user')
    })
  })

  // ------------------------------------------------------------------
  // 3. Done signal
  // ------------------------------------------------------------------
  describe('done signal', () => {
    it('should set isStreaming to false and close EventSource', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Hello')
      })

      const es = lastEventSourceInstance!

      // Send some tokens first
      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"token":"text"}' }))
      })

      // Send done signal
      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"done":true}' }))
      })

      expect(result.current.isStreaming).toBe(false)
      expect(result.current.messages[1].isStreaming).toBe(false)
      expect(lastEventSourceInstance).toBeNull() // closed
    })

    it('should preserve the full accumulated content after done', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Query')
      })

      const es = lastEventSourceInstance!

      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"token":"A"}' }))
      })
      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"token":"nswer"}' }))
      })
      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"done":true}' }))
      })

      expect(result.current.messages[1].content).toBe('Answer')
    })
  })

  // ------------------------------------------------------------------
  // 4. Error handling
  // ------------------------------------------------------------------
  describe('error handling', () => {
    it('should retry up to MAX_RETRIES times before setting permanent error', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Hello')
      })

      const es = lastEventSourceInstance!

      // Error 1 — still streaming, no error set
      act(() => { es.onerror?.() })
      expect(result.current.error).toBeNull()
      expect(result.current.isStreaming).toBe(true)

      // Error 2 — still streaming, no error set
      act(() => { es.onerror?.() })
      expect(result.current.error).toBeNull()
      expect(result.current.isStreaming).toBe(true)

      // Error 3 (MAX_RETRIES reached) — error set, streaming stops
      act(() => { es.onerror?.() })
      expect(result.current.error).toBe('连接失败，请稍后重试')
      expect(result.current.isStreaming).toBe(false)
    })

    it('should preserve partial content with interruption suffix on max retries', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Hello')
      })

      const es = lastEventSourceInstance!
      const assistantId = result.current.messages[1].id

      // Send some tokens
      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"token":"Partial "}' }))
      })
      act(() => {
        es.onmessage?.(new MessageEvent('message', { data: '{"token":"response"}' }))
      })

      // Trigger 3 errors
      for (let i = 0; i < 3; i++) {
        act(() => { es.onerror?.() })
      }

      const assistant = result.current.messages.find(m => m.id === assistantId)
      expect(assistant?.content).toBe('Partial response[连接中断]')
      expect(assistant?.isStreaming).toBe(false)
    })

    it('should close EventSource after max retries', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Hello')
      })

      const es = lastEventSourceInstance!

      for (let i = 0; i < 3; i++) {
        act(() => { es.onerror?.() })
      }

      expect(lastEventSourceInstance).toBeNull()
    })

    it('should abort old connection and create new one when sending again', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('msg1')
      })

      const es1 = lastEventSourceInstance!
      expect(es1).not.toBeNull()

      // Start a new message — this sets abortRef.current = true, closes es1,
      // then creates a new EventSource for msg2
      act(() => {
        result.current.sendMessage('msg2')
      })

      const es2 = lastEventSourceInstance!
      // New EventSource instance should be created for msg2
      expect(es2).not.toBe(es1)
      // Messages from both sends should be present
      expect(result.current.messages).toHaveLength(4) // 2 from msg1 + 2 from msg2
    })
  })

  // ------------------------------------------------------------------
  // 5. clearError
  // ------------------------------------------------------------------
  describe('clearError', () => {
    it('should clear error and reset retry count', () => {
      const { result } = renderHook(() => useChat())

      act(() => {
        result.current.sendMessage('Hello')
      })

      const es = lastEventSourceInstance!
      for (let i = 0; i < 3; i++) {
        act(() => { es.onerror?.() })
      }

      expect(result.current.error).not.toBeNull()

      act(() => {
        result.current.clearError()
      })

      expect(result.current.error).toBeNull()
    })
  })
})
