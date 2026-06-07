import { useState, useRef, useEffect, useCallback, type KeyboardEvent } from 'react'

interface ChatInputProps {
  onSend: (content: string) => void;
  disabled: boolean;
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const trimmed = value.trim()
  const isSendDisabled = disabled || !trimmed

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`
  }, [value])

  const handleSend = useCallback(() => {
    if (isSendDisabled) return
    onSend(value)
    setValue('')
  }, [value, isSendDisabled, onSend])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex-shrink-0 border-t border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="输入消息..."
          rows={1}
          className="flex-1 border border-[#d1d1d6] rounded-2xl p-2.5 px-4 bg-white dark:bg-gray-800 dark:text-white dark:border-gray-600 resize-none min-h-[40px] max-h-32 overflow-y-auto outline-none focus:border-[#007aff] focus:ring-1 focus:ring-[#007aff]"
        />
        <button
          onClick={handleSend}
          disabled={isSendDisabled}
          aria-label="发送消息"
          className="flex-shrink-0 w-10 h-10 rounded-full bg-[#007aff] text-white flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#0056cc] transition-colors"
        >
          ▸
        </button>
      </div>
    </div>
  )
}
