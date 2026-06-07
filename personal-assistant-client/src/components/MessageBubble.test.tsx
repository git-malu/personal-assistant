import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageBubble } from './MessageBubble'
import type { Message } from '../types/chat'

describe('MessageBubble', () => {
  // ------------------------------------------------------------------
  // 1. User bubble
  // ------------------------------------------------------------------
  describe('user bubble', () => {
    it('should render with blue background color class', () => {
      const msg: Message = {
        id: '1',
        role: 'user',
        content: 'Hello',
        timestamp: Date.now(),
      }

      render(<MessageBubble message={msg} />)

      const bubble = screen.getByText('Hello').closest('.max-w-\\[75\\%\\]')
      expect(bubble).toHaveClass('bg-primary')
      expect(bubble).toHaveClass('text-primary-foreground')
    })

    it('should be right-aligned', () => {
      const msg: Message = {
        id: '1',
        role: 'user',
        content: 'Hello',
        timestamp: Date.now(),
      }

      const { container } = render(<MessageBubble message={msg} />)

      // The outer wrapper has 'items-end' for user
      const wrapper = container.firstElementChild
      expect(wrapper).toHaveClass('items-end')
      expect(wrapper).not.toHaveClass('items-start')
    })

    it('should not show streaming cursor for regular user messages', () => {
      const msg: Message = {
        id: '1',
        role: 'user',
        content: 'Hello',
        timestamp: Date.now(),
      }

      render(<MessageBubble message={msg} />)

      const cursor = document.querySelector('.cursor-blink')
      expect(cursor).toBeNull()
    })
  })

  // ------------------------------------------------------------------
  // 2. Assistant bubble
  // ------------------------------------------------------------------
  describe('assistant bubble', () => {
    it('should render with gray background color class', () => {
      const msg: Message = {
        id: '2',
        role: 'assistant',
        content: 'Hi there',
        timestamp: Date.now(),
      }

      render(<MessageBubble message={msg} />)

      const bubble = screen.getByText('Hi there').closest('.max-w-\\[75\\%\\]')
      expect(bubble).toHaveClass('bg-muted')
    })

    it('should be left-aligned', () => {
      const msg: Message = {
        id: '2',
        role: 'assistant',
        content: 'Hi there',
        timestamp: Date.now(),
      }

      const { container } = render(<MessageBubble message={msg} />)

      const wrapper = container.firstElementChild
      expect(wrapper).toHaveClass('items-start')
      expect(wrapper).not.toHaveClass('items-end')
    })
  })

  // ------------------------------------------------------------------
  // 3. Streaming cursor
  // ------------------------------------------------------------------
  describe('streaming cursor', () => {
    it('should show cursor-blink element when isStreaming is true', () => {
      const msg: Message = {
        id: '3',
        role: 'assistant',
        content: 'Partial...',
        timestamp: Date.now(),
        isStreaming: true,
      }

      render(<MessageBubble message={msg} />)

      const cursor = document.querySelector('.cursor-blink')
      expect(cursor).toBeInTheDocument()
    })

    it('should not show cursor-blink element when isStreaming is false', () => {
      const msg: Message = {
        id: '4',
        role: 'assistant',
        content: 'Complete',
        timestamp: Date.now(),
        isStreaming: false,
      }

      render(<MessageBubble message={msg} />)

      const cursor = document.querySelector('.cursor-blink')
      expect(cursor).toBeNull()
    })

    it('should not show cursor-blink when isStreaming is undefined', () => {
      const msg: Message = {
        id: '5',
        role: 'assistant',
        content: 'Complete',
        timestamp: Date.now(),
        // isStreaming is undefined
      }

      render(<MessageBubble message={msg} />)

      const cursor = document.querySelector('.cursor-blink')
      expect(cursor).toBeNull()
    })
  })
})
