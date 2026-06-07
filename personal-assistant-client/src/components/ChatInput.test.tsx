import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatInput } from './ChatInput'

describe('ChatInput', () => {
  // ------------------------------------------------------------------
  // 1. Enter key sends message
  // ------------------------------------------------------------------
  it('should call onSend when Enter is pressed', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<ChatInput onSend={onSend} disabled={false} />)

    const textarea = screen.getByPlaceholderText('输入消息...')
    await user.type(textarea, 'Hello world')
    await user.keyboard('{Enter}')

    expect(onSend).toHaveBeenCalledWith('Hello world')
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  // ------------------------------------------------------------------
  // 2. Shift+Enter inserts newline
  // ------------------------------------------------------------------
  it('should insert a newline on Shift+Enter instead of sending', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<ChatInput onSend={onSend} disabled={false} />)

    const textarea = screen.getByPlaceholderText('输入消息...')
    await user.type(textarea, 'Line1')
    await user.keyboard('{Shift>}{Enter}{/Shift}')
    await user.type(textarea, 'Line2')

    expect(textarea).toHaveValue('Line1\nLine2')
    expect(onSend).not.toHaveBeenCalled()
  })

  // ------------------------------------------------------------------
  // 3. Send button disabled when isStreaming
  // ------------------------------------------------------------------
  it('should disable textarea and send button when disabled prop is true', () => {
    render(<ChatInput onSend={vi.fn()} disabled={true} />)

    const textarea = screen.getByPlaceholderText('输入消息...')
    const button = screen.getByRole('button', { name: '发送消息' })

    expect(textarea).toBeDisabled()
    expect(button).toBeDisabled()
  })

  it('should enable textarea and send button when disabled prop is false', () => {
    render(<ChatInput onSend={vi.fn()} disabled={false} />)

    const textarea = screen.getByPlaceholderText('输入消息...')
    const button = screen.getByRole('button', { name: '发送消息' })

    expect(textarea).not.toBeDisabled()
    // Button should still be disabled when input is empty
    expect(button).toBeDisabled()
  })

  // ------------------------------------------------------------------
  // 4. Empty/whitespace content disables send
  // ------------------------------------------------------------------
  it('should disable send button when input is empty', () => {
    render(<ChatInput onSend={vi.fn()} disabled={false} />)

    const button = screen.getByRole('button', { name: '发送消息' })
    expect(button).toBeDisabled()
  })

  it('should disable send button when input is only whitespace', async () => {
    const user = userEvent.setup()
    render(<ChatInput onSend={vi.fn()} disabled={false} />)

    const textarea = screen.getByPlaceholderText('输入消息...')
    await user.type(textarea, '   ')

    const button = screen.getByRole('button', { name: '发送消息' })
    expect(button).toBeDisabled()
  })

  it('should enable send button when there is content', async () => {
    const user = userEvent.setup()
    render(<ChatInput onSend={vi.fn()} disabled={false} />)

    const textarea = screen.getByPlaceholderText('输入消息...')
    await user.type(textarea, 'Hi')

    const button = screen.getByRole('button', { name: '发送消息' })
    expect(button).toBeEnabled()
  })

  // ------------------------------------------------------------------
  // 5. Click send button
  // ------------------------------------------------------------------
  it('should call onSend when send button is clicked', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<ChatInput onSend={onSend} disabled={false} />)

    const textarea = screen.getByPlaceholderText('输入消息...')
    await user.type(textarea, 'Click send')

    const button = screen.getByRole('button', { name: '发送消息' })
    await user.click(button)

    expect(onSend).toHaveBeenCalledWith('Click send')
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  // ------------------------------------------------------------------
  // 6. Enter should not send when disabled
  // ------------------------------------------------------------------
  it('should not send on Enter when disabled', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<ChatInput onSend={onSend} disabled={true} />)

    // Even though textarea is disabled, Enter should not trigger onSend
    await user.keyboard('{Enter}')

    expect(onSend).not.toHaveBeenCalled()
  })

  // ------------------------------------------------------------------
  // 7. Clearing input after send
  // ------------------------------------------------------------------
  it('should clear the input after sending via Enter', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<ChatInput onSend={onSend} disabled={false} />)

    const textarea = screen.getByPlaceholderText('输入消息...') as HTMLTextAreaElement
    await user.type(textarea, 'Test')
    await user.keyboard('{Enter}')

    expect(textarea.value).toBe('')
  })

  it('should clear the input after sending via button click', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<ChatInput onSend={onSend} disabled={false} />)

    const textarea = screen.getByPlaceholderText('输入消息...') as HTMLTextAreaElement
    await user.type(textarea, 'Test')

    const button = screen.getByRole('button', { name: '发送消息' })
    await user.click(button)

    expect(textarea.value).toBe('')
  })
})
