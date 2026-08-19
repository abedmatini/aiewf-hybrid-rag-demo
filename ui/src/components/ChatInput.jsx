import { useState, useRef, forwardRef } from 'react'
import './ChatInput.css'

const ChatInput = forwardRef(function ChatInput({ onSend, disabled, placeholder }, forwardedRef) {
  const [text, setText] = useState('')
  const internalRef = useRef(null)
  // Use the forwarded ref when provided (allows parent to return focus here)
  const textareaRef = forwardedRef ?? internalRef

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function submit() {
    if (!text.trim() || disabled) return
    onSend(text.trim())
    setText('')
    textareaRef.current?.focus()
  }

  return (
    <div className="input-bar">
      <textarea
        ref={textareaRef}
        className="input-textarea"
        placeholder={placeholder || 'Ask a question… (Enter to send, Shift+Enter for new line)'}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={1}
        aria-label="Type your message"
      />
      <button
        className="input-send"
        onClick={submit}
        disabled={disabled || !text.trim()}
        aria-label="Send message"
      >
        {disabled ? '…' : '↑'}
      </button>
    </div>
  )
})

export default ChatInput
