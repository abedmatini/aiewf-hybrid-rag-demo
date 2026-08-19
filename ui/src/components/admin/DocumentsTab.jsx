import { useState, useEffect, useRef } from 'react'
import ChunksModal from './ChunksModal.jsx'
import './DocumentsTab.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8003'

const STRATEGIES = [
  { value: 'heading',   label: 'Heading-based (default)' },
  { value: 'paragraph', label: 'Paragraph' },
  { value: 'fixed',     label: 'Fixed 512-char + overlap' },
  { value: 'sentence',  label: 'Sentence groups' },
]

const SCREENSHOT_STRATEGY_OPTIONS = [
  STRATEGIES.find(s => s.value === 'sentence'),
  ...STRATEGIES.filter(s => s.value !== 'sentence'),
]

export default function DocumentsTab() {
  const [docs, setDocs]           = useState([])
  const [strategy, setStrategy]   = useState('heading')
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState('')
  const [viewingDoc, setViewingDoc] = useState(null)

  // Screenshot flow: idle → extracting → preview → indexing → done
  const [shotPhase, setShotPhase]       = useState('idle')
  const [shotMsg, setShotMsg]           = useState('')
  const [shotPreview, setShotPreview]   = useState(null) // { doc_hash, filename, extracted_text }
  const [shotText, setShotText]         = useState('')
  const [shotStrategy, setShotStrategy] = useState('sentence')

  const fileRef = useRef(null)
  const shotRef = useRef(null)

  useEffect(() => { loadDocs() }, [])

  async function loadDocs() {
    try {
      const resp = await fetch(`${API}/documents`)
      if (resp.ok) setDocs(await resp.json())
    } catch {}
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    await doUpload(file)
  }

  async function doUpload(file) {
    setUploading(true)
    setUploadMsg(`Uploading "${file.name}"…`)

    const form = new FormData()
    form.append('file', file)
    form.append('strategy', strategy)

    try {
      setUploadMsg(`Parsing with Docling…`)
      const resp = await fetch(`${API}/documents/upload`, { method: 'POST', body: form })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || 'Upload failed')
      if (data.already_existed) {
        setUploadMsg(`Already indexed: ${file.name}`)
      } else {
        const chunks = data.chunk_count ? ` (${data.chunk_count} chunks)` : ''
        setUploadMsg(`✓ Indexed: ${file.name}${chunks}`)
      }
      await loadDocs()
    } catch (err) {
      setUploadMsg(`Error: ${err.message}`)
    }

    setUploading(false)
  }

  async function handleScreenshotChange(e) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    await extractScreenshot(file)
  }

  async function extractScreenshot(file) {
    setShotPhase('extracting')
    setShotMsg('Uploading screenshot…')
    setShotPreview(null)

    const form = new FormData()
    form.append('file', file)

    try {
      setShotMsg('Extracting text with vision model (this may take a minute)…')
      const resp = await fetch(`${API}/documents/screenshot/extract`, { method: 'POST', body: form })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || 'Extraction failed')

      setShotPreview({
        doc_hash: data.doc_hash,
        filename: data.filename,
        vision_model: data.vision_model,
      })
      setShotText(data.extracted_text)
      setShotStrategy(data.strategy || 'sentence')
      setShotPhase('preview')
      setShotMsg(`Text extracted from "${data.filename}" — review below, then index.`)
    } catch (err) {
      setShotPhase('error')
      setShotMsg(`Error: ${err.message}`)
    }
  }

  async function confirmScreenshot() {
    if (!shotPreview || !shotText.trim()) return

    setShotPhase('indexing')
    setShotMsg('Chunking and embedding…')

    try {
      const resp = await fetch(`${API}/documents/screenshot/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          doc_hash: shotPreview.doc_hash,
          filename: shotPreview.filename,
          markdown_text: shotText,
          strategy: shotStrategy,
        }),
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || 'Indexing failed')

      const chunks = data.chunk_count ? ` (${data.chunk_count} chunks)` : ''
      setShotPhase('done')
      setShotMsg(
        data.already_existed
          ? `Already indexed: ${shotPreview.filename}`
          : `✓ Indexed screenshot: ${shotPreview.filename}${chunks}`,
      )
      setShotPreview(null)
      setShotText('')
      await loadDocs()
    } catch (err) {
      setShotPhase('error')
      setShotMsg(`Error: ${err.message}`)
    }
  }

  function cancelScreenshot() {
    setShotPhase('idle')
    setShotMsg('')
    setShotPreview(null)
    setShotText('')
    setShotStrategy('sentence')
  }

  async function docAction(docId, action) {
    try {
      const url    = action === 'delete' ? `${API}/documents/${docId}` : `${API}/documents/${docId}/${action}`
      const method = action === 'delete' ? 'DELETE' : 'PATCH'
      await fetch(url, { method })
      await loadDocs()
    } catch {}
  }

  function confirmDelete(doc) {
    if (window.confirm(`Permanently delete "${doc.filename}"?\n\nThis cannot be undone.`)) {
      docAction(doc.id, 'delete')
    }
  }

  const shotBusy = shotPhase === 'extracting' || shotPhase === 'indexing'

  return (
    <div className="docs-tab">
      {/* ── Document upload ──────────────────────────────────── */}
      <section className="docs-tab__upload">
        <h2 className="docs-tab__heading">Upload document</h2>
        <p className="docs-tab__hint">
          PDF, PPTX, DOCX, XLSX, MD, TXT — parsed by Docling, chunked and embedded automatically.
        </p>
        <div className="upload-controls">
          <label className="upload-controls__label">Chunking strategy</label>
          <select
            className="upload-controls__select"
            value={strategy}
            onChange={e => setStrategy(e.target.value)}
            disabled={uploading}
          >
            {STRATEGIES.map(s => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
          <button
            className="upload-controls__btn"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'Uploading…' : 'Choose file'}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.pptx,.docx,.xlsx,.md,.txt"
            style={{ display: 'none' }}
            onChange={handleFileChange}
          />
        </div>
        {uploadMsg && (
          <p className={`upload-feedback ${uploadMsg.startsWith('Error') ? 'upload-feedback--error' : 'upload-feedback--ok'}`}>
            {uploadMsg}
          </p>
        )}
      </section>

      {/* ── Screenshot upload ─────────────────────────────────── */}
      <section className="docs-tab__upload docs-tab__upload--screenshot">
        <h2 className="docs-tab__heading">Upload screenshot or image</h2>
        <p className="docs-tab__hint">
          Email alerts, Slack messages, maintenance notices — extracted with a local vision model,
          then indexed after you review the text. Sentence chunking is recommended.
        </p>

        {shotPhase === 'idle' || shotPhase === 'done' || shotPhase === 'error' ? (
          <div className="upload-controls">
            <button
              className="upload-controls__btn upload-controls__btn--secondary"
              onClick={() => shotRef.current?.click()}
              disabled={shotBusy}
            >
              Choose screenshot
            </button>
            <input
              ref={shotRef}
              type="file"
              accept=".png,.jpg,.jpeg,.webp,.gif,image/png,image/jpeg,image/webp,image/gif"
              style={{ display: 'none' }}
              onChange={handleScreenshotChange}
            />
          </div>
        ) : null}

        {shotPhase === 'preview' && (
          <div className="screenshot-preview">
            <div className="upload-controls screenshot-preview__controls">
              <label className="upload-controls__label">Chunking strategy</label>
              <select
                className="upload-controls__select"
                value={shotStrategy}
                onChange={e => setShotStrategy(e.target.value)}
              >
                {SCREENSHOT_STRATEGY_OPTIONS.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <label className="screenshot-preview__label" htmlFor="screenshot-text">
              Extracted text {shotPreview?.vision_model ? `(via ${shotPreview.vision_model})` : ''}
            </label>
            <textarea
              id="screenshot-text"
              className="screenshot-preview__textarea"
              value={shotText}
              onChange={e => setShotText(e.target.value)}
              rows={12}
            />
            <div className="screenshot-preview__actions">
              <button
                className="upload-controls__btn"
                onClick={confirmScreenshot}
                disabled={!shotText.trim()}
              >
                Index into knowledge base
              </button>
              <button
                className="upload-controls__btn upload-controls__btn--ghost"
                onClick={cancelScreenshot}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {shotMsg && (
          <p className={`upload-feedback ${
            shotMsg.startsWith('Error') ? 'upload-feedback--error'
            : shotPhase === 'extracting' || shotPhase === 'indexing' ? 'upload-feedback--progress'
            : 'upload-feedback--ok'
          }`}>
            {(shotPhase === 'extracting' || shotPhase === 'indexing') && (
              <span className="upload-spinner" aria-hidden="true" />
            )}
            {shotMsg}
          </p>
        )}
      </section>

      {/* ── Document list ───────────────────────────────────── */}
      <section className="docs-tab__list">
        <h2 className="docs-tab__heading">
          Knowledge base
          <span className="docs-tab__count">{docs.length} document{docs.length !== 1 ? 's' : ''}</span>
        </h2>

        {docs.length === 0 ? (
          <p className="docs-empty">No documents indexed yet. Upload your first document above.</p>
        ) : (
          <div className="docs-table-wrapper">
            <table className="docs-table">
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Strategy</th>
                  <th>Chunks</th>
                  <th>Status</th>
                  <th>Uploaded</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {docs.map(doc => (
                  <tr key={doc.id} className={`docs-table__row docs-table__row--${doc.status}`}>
                    <td className="docs-table__name" title={doc.filename}>{doc.filename}</td>
                    <td>{doc.strategy}</td>
                    <td>{doc.chunk_count}</td>
                    <td>
                      <span className={`status-pill status-pill--${doc.status}`}>
                        {doc.status}
                      </span>
                    </td>
                    <td>{new Date(doc.uploaded_at).toLocaleDateString()}</td>
                    <td className="docs-table__actions">
                      <button
                        className="action-btn action-btn--chunks"
                        onClick={() => setViewingDoc(doc)}
                        title="View & edit chunks"
                      >
                        Chunks ({doc.chunk_count})
                      </button>
                      {doc.status === 'active' && (
                        <button
                          className="action-btn action-btn--archive"
                          onClick={() => docAction(doc.id, 'archive')}
                        >
                          Archive
                        </button>
                      )}
                      {doc.status === 'archived' && (
                        <button
                          className="action-btn action-btn--restore"
                          onClick={() => docAction(doc.id, 'restore')}
                        >
                          Restore
                        </button>
                      )}
                      <button
                        className="action-btn action-btn--delete"
                        onClick={() => confirmDelete(doc)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {viewingDoc && (
        <ChunksModal doc={viewingDoc} onClose={() => setViewingDoc(null)} />
      )}
    </div>
  )
}
