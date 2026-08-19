import { useState, useRef } from 'react'
import './UploadButton.css'

const ACCEPTED = '.pdf,.pptx,.docx,.xlsx,.html,.md,.txt'

export default function UploadButton({ userId, apiUrl }) {
  const [status, setStatus]     = useState('idle')   // idle | uploading | done | error
  const [message, setMessage]   = useState('')
  const inputRef = useRef(null)

  async function handleFile(file) {
    if (!file) return
    setStatus('uploading')
    setMessage(`Uploading ${file.name}…`)

    const form = new FormData()
    form.append('file', file)
    form.append('user_id', userId)
    form.append('strategy', 'heading')

    try {
      const resp = await fetch(`${apiUrl}/documents/upload`, {
        method: 'POST',
        body: form,
      })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }))
        throw new Error(err.detail || 'Upload failed')
      }
      const data = await resp.json()
      setStatus('done')
      setMessage(
        data.already_existed
          ? `Already indexed: ${file.name}`
          : `Indexed: ${file.name}`
      )
    } catch (err) {
      setStatus('error')
      setMessage(err.message)
    }

    setTimeout(() => { setStatus('idle'); setMessage('') }, 4000)
  }

  return (
    <div className="upload">
      <button
        className={`upload-btn upload-btn--${status}`}
        onClick={() => inputRef.current?.click()}
        disabled={status === 'uploading'}
      >
        {status === 'uploading' ? '⏳ Uploading…' : '+ Upload document'}
      </button>
      {message && (
        <p className={`upload-msg upload-msg--${status}`}>{message}</p>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        style={{ display: 'none' }}
        onChange={e => handleFile(e.target.files?.[0])}
      />
    </div>
  )
}
