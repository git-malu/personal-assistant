import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageList } from './MessageList'
import type { Message } from '../types/chat'

describe('MessageList', () => {
  // ------------------------------------------------------------------
  // 1. Renders messages
  // ------------------------------------------------------------------
  it('should render all messages', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: 'Hello', timestamp: 1000 },
      { id: '2', role: 'assistant', content: 'Hi there!', timestamp: 1001 },
      { id: '3', role: 'user', content: 'How are you?', timestamp: 1002 },
    ]

    render(<MessageList messages={messages} />)

    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.getByText('Hi there!')).toBeInTheDocument()
    expect(screen.getByText('How are you?')).toBeInTheDocument()
  })

  it('should render empty list without error when messages is empty', () => {
    const { container } = render(<MessageList messages={[]} />)

    // The scrollable container should exist
    expect(container.firstElementChild).toBeInTheDocument()
    // No message bubbles
    expect(container.querySelectorAll('.mb-4')).toHaveLength(0)
  })

  // ------------------------------------------------------------------
  // 2. Auto-scroll to bottom
  // ------------------------------------------------------------------
  it('should set scrollTop to scrollHeight when messages change', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: 'Hello', timestamp: 1000 },
    ]

    const { container, rerender } = render(<MessageList messages={messages} />)

    const scrollContainer = container.firstElementChild as HTMLDivElement

    // Mock scrollHeight so we can assert scrollTop equals it
    Object.defineProperty(scrollContainer, 'scrollHeight', {
      value: 500,
      writable: true,
      configurable: true,
    })

    // Update messages to trigger the useEffect
    const updatedMessages: Message[] = [
      ...messages,
      { id: '2', role: 'assistant', content: 'Response', timestamp: 1001 },
    ]
    rerender(<MessageList messages={updatedMessages} />)

    // Since isNearBottomRef starts as true, scrollTop should be set to scrollHeight
    expect(scrollContainer.scrollTop).toBe(500)
  })

  // ------------------------------------------------------------------
  // 3. User scroll tracking
  // ------------------------------------------------------------------
  it('should NOT auto-scroll when user has scrolled up', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: 'Hello', timestamp: 1000 },
    ]

    const { container, rerender } = render(<MessageList messages={messages} />)

    const scrollContainer = container.firstElementChild as HTMLDivElement

    // Simulate: user scrolled up (far from bottom)
    Object.defineProperty(scrollContainer, 'scrollHeight', {
      value: 1000,
      writable: true,
      configurable: true,
    })
    Object.defineProperty(scrollContainer, 'scrollTop', {
      value: 100, // user is near the top
      writable: true,
      configurable: true,
    })
    Object.defineProperty(scrollContainer, 'clientHeight', {
      value: 400,
      writable: true,
      configurable: true,
    })

    // Fire scroll event to update isNearBottomRef
    scrollContainer.dispatchEvent(new Event('scroll'))

    // Save the current scrollTop
    const scrollTopBefore = scrollContainer.scrollTop

    const updatedMessages: Message[] = [
      ...messages,
      { id: '2', role: 'assistant', content: 'Response', timestamp: 1001 },
    ]
    rerender(<MessageList messages={updatedMessages} />)

    // scrollTop should NOT have changed to scrollHeight
    expect(scrollContainer.scrollTop).toBe(scrollTopBefore)
  })

  it('should auto-scroll when user is near the bottom', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: 'Hello', timestamp: 1000 },
    ]

    const { container, rerender } = render(<MessageList messages={messages} />)

    const scrollContainer = container.firstElementChild as HTMLDivElement

    // Simulate: user near the bottom (within 100px threshold)
    Object.defineProperty(scrollContainer, 'scrollHeight', {
      value: 1000,
      writable: true,
      configurable: true,
    })
    Object.defineProperty(scrollContainer, 'scrollTop', {
      value: 910, // 1000 - 910 - 400 = -310 which is < 100
      writable: true,
      configurable: true,
    })
    Object.defineProperty(scrollContainer, 'clientHeight', {
      value: 400,
      writable: true,
      configurable: true,
    })

    // Fire scroll event
    scrollContainer.dispatchEvent(new Event('scroll'))

    const updatedMessages: Message[] = [
      ...messages,
      { id: '2', role: 'assistant', content: 'Response', timestamp: 1001 },
    ]
    rerender(<MessageList messages={updatedMessages} />)

    // scrollTop should now be set to scrollHeight
    expect(scrollContainer.scrollTop).toBe(1000)
  })
})
