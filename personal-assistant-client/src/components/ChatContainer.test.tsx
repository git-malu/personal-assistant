import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatContainer } from './ChatContainer'

// Mock useChat to isolate ChatContainer's rendering/error flow
vi.mock('../hooks/useChat', () => ({
  useChat: vi.fn(),
}))

import { useChat } from '../hooks/useChat'

function mockUseChat(overrides: Record<string, unknown> = {}) {
  const mockFn = useChat as ReturnType<typeof vi.fn>
  mockFn.mockReturnValue({
    messages: [],
    sendMessage: vi.fn(),
    isStreaming: false,
    error: null,
    clearError: vi.fn(),
    ...overrides,
  })
}

describe('ChatContainer', () => {
  // ------------------------------------------------------------------
  // 1. Basic rendering
  // ------------------------------------------------------------------
  it('should render the header', () => {
    mockUseChat()
    render(<ChatContainer />)
    expect(screen.getByText('Personal Assistant')).toBeInTheDocument()
  })

  it('should render chat input', () => {
    mockUseChat()
    render(<ChatContainer />)
    expect(screen.getByPlaceholderText('输入消息...')).toBeInTheDocument()
  })

  // ------------------------------------------------------------------
  // 2. Error alert (shadcn Alert component)
  // ------------------------------------------------------------------
  it('should not show alert when there is no error', () => {
    mockUseChat({ error: null })
    render(<ChatContainer />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('should show destructive alert with error message', () => {
    mockUseChat({ error: '测试错误信息' })
    render(<ChatContainer />)
    // Alert component has role="alert" for accessibility
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('测试错误信息')).toBeInTheDocument()
  })

  // ------------------------------------------------------------------
  // 3. Error dismiss interaction
  // ------------------------------------------------------------------
  it('should call clearError when dismiss button is clicked', async () => {
    const clearError = vi.fn()
    mockUseChat({ error: '可关闭的错误', clearError })
    const user = userEvent.setup()
    render(<ChatContainer />)

    await user.click(screen.getByText('×'))

    expect(clearError).toHaveBeenCalledTimes(1)
  })

  // ------------------------------------------------------------------
  // 4. Error cleared on new send (integration)
  // ------------------------------------------------------------------
  it('should not show error after clearError is called', () => {
    const clearError = vi.fn()
    // First render with error
    mockUseChat({ error: '可关闭的错误', clearError })
    const { rerender } = render(<ChatContainer />)
    expect(screen.getByRole('alert')).toBeInTheDocument()

    // Re-render with error cleared
    mockUseChat({ error: null, clearError })
    rerender(<ChatContainer />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
