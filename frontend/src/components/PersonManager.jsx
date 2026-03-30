import { useState, useEffect, useRef } from 'react'
import '../styles/PersonManager.css'

const API = 'http://localhost:8000/files'

export default function PersonManager({ onPersonsChange }) {
  const [persons, setPersons] = useState([])
  const [photos, setPhotos] = useState({})          // { personId: [photo, …] }
  const [editingId, setEditingId] = useState(null)
  const [editName, setEditName] = useState('')
  const [mergeSource, setMergeSource] = useState(null)
  const [loadingPhotos, setLoadingPhotos] = useState({})
  const [expandedId, setExpandedId] = useState(null)
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef(null)
  const personGridRef = useRef(null)
  const dragStartXRef = useRef(0)
  const dragStartScrollRef = useRef(0)
  const pointerHistoryRef = useRef([])
  const velocityRef = useRef(0)
  const momentumFrameRef = useRef(null)
  const momentumLastTimeRef = useRef(0)
  const loadedThumbnailsRef = useRef(new Set())
  const MOMENTUM_MULTIPLIER = 4

  useEffect(() => { fetchPersons() }, [])
  useEffect(() => { if (editingId && inputRef.current) inputRef.current.focus() }, [editingId])

  const fetchPersons = async () => {
    try {
      const res = await fetch(`${API}/persons`)
      if (res.ok) {
        const data = await res.json()
        setPersons(data)
        onPersonsChange?.(data)
      }
    } catch (e) { console.error(e) }
  }

  const fetchPhotos = async (personId, expand = true) => {
    if (photos[personId]) {
      if (expand) setExpandedId(expandedId === personId ? null : personId)
      return
    }
    setLoadingPhotos(p => ({ ...p, [personId]: true }))
    try {
      const res = await fetch(`${API}/persons/${personId}/photos`)
      if (res.ok) {
        const data = await res.json()
        setPhotos(p => ({ ...p, [personId]: data }))
        loadedThumbnailsRef.current.add(personId)
        if (expand) setExpandedId(personId)
      }
    } catch (e) { console.error(e) }
    finally { setLoadingPhotos(p => ({ ...p, [personId]: false })) }
  }

  const saveName = async (id) => {
    if (!editName.trim()) return
    try {
      const res = await fetch(`${API}/persons/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: editName.trim() }),
      })
      if (res.ok) {
        // FIX: invalidate this person's cached photo list so the avatar
        // thumbnail re-fetches on next expand (the photo URL itself doesn't
        // change, but person_name on each File record was updated server-side).
        setPhotos(p => { const next = { ...p }; delete next[id]; return next })
        await fetchPersons()
      }
    } catch (e) { console.error(e) }
    setEditingId(null)
  }

  const startMerge = (id) => {
    setMergeSource(id)
    setExpandedId(null)
  }

  useEffect(() => {
    if (!persons.length) return
    persons.forEach(person => {
      if (!loadedThumbnailsRef.current.has(person.id) && !photos[person.id]) {
        fetchPhotos(person.id, false)
      }
    })
  }, [persons])

  const stopMomentum = () => {
    if (momentumFrameRef.current) {
      cancelAnimationFrame(momentumFrameRef.current)
      momentumFrameRef.current = null
    }
  }

  const startMomentum = () => {
    const grid = personGridRef.current
    if (!grid) return

    stopMomentum()
    momentumLastTimeRef.current = performance.now()

    const step = (timestamp) => {
      const gridEl = personGridRef.current
      if (!gridEl) return

      const delta = timestamp - momentumLastTimeRef.current
      momentumLastTimeRef.current = timestamp
      let velocity = velocityRef.current
      if (Math.abs(velocity) < 0.01) {
        stopMomentum()
        return
      }

      const nextScroll = gridEl.scrollLeft + velocity * delta
      const maxScroll = gridEl.scrollWidth - gridEl.clientWidth
      if (nextScroll <= 0 || nextScroll >= maxScroll) {
        stopMomentum()
        return
      }

      gridEl.scrollLeft = nextScroll
      const decay = Math.pow(0.92, delta / 16)
      velocityRef.current = velocity * decay
      momentumFrameRef.current = requestAnimationFrame(step)
    }

    momentumFrameRef.current = requestAnimationFrame(step)
  }

  const handleGridPointerDown = (e) => {
    if (e.button !== 0) return
    if (e.target.closest('button, input, select, textarea')) return
    const grid = personGridRef.current
    if (!grid) return

    stopMomentum()
    const rect = grid.getBoundingClientRect()
    setIsDragging(true)
    dragStartXRef.current = e.clientX - rect.left
    dragStartScrollRef.current = grid.scrollLeft
    pointerHistoryRef.current = [{ x: e.clientX, time: performance.now() }]
    velocityRef.current = 0
    grid.setPointerCapture?.(e.pointerId)
    e.preventDefault()
  }

  const handleGridPointerMove = (e) => {
    if (!isDragging) return
    const grid = personGridRef.current
    if (!grid) return

    const rect = grid.getBoundingClientRect()
    const x = e.clientX - rect.left
    const walk = x - dragStartXRef.current
    grid.scrollLeft = dragStartScrollRef.current - walk

    const now = performance.now()
    const history = pointerHistoryRef.current
    history.push({ x: e.clientX, time: now })
    while (history.length > 10) {
      history.shift()
    }
    pointerHistoryRef.current = history

    if (history.length >= 2) {
      const recent = history.slice(-4)
      const first = recent[0]
      const last = recent[recent.length - 1]
      const dt = Math.max(last.time - first.time, 16)
      const deltaX = last.x - first.x
      velocityRef.current = -(deltaX / dt) * MOMENTUM_MULTIPLIER
    }
  }

  const stopGridDrag = (e) => {
    if (!isDragging) return
    setIsDragging(false)

    const grid = personGridRef.current
    if (!grid) return

    if (e?.pointerId) {
      grid.releasePointerCapture?.(e.pointerId)
    }

    const now = performance.now()
    const history = pointerHistoryRef.current
    const lastPoint = history[history.length - 1]
    if (!lastPoint || lastPoint.x !== e.clientX) {
      history.push({ x: e.clientX, time: now })
    }
    if (history.length >= 2) {
      const recent = history.slice(-4)
      const first = recent[0]
      const last = recent[recent.length - 1]
      const dt = Math.max(last.time - first.time, 16)
      const deltaX = last.x - first.x
      velocityRef.current = -(deltaX / dt) * MOMENTUM_MULTIPLIER
    }
    pointerHistoryRef.current = []

    if (Math.abs(velocityRef.current) > 0.02) {
      startMomentum()
    }
  }

  useEffect(() => {
    if (!isDragging) return

    const onPointerMove = (e) => handleGridPointerMove(e)
    const onPointerUp = (e) => stopGridDrag(e)
    const onPointerCancel = (e) => stopGridDrag(e)

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    window.addEventListener('pointercancel', onPointerCancel)

    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      window.removeEventListener('pointercancel', onPointerCancel)
    }
  }, [isDragging])

  const confirmMerge = async (targetId) => {
    if (!mergeSource || mergeSource === targetId) return
    const sourceId = mergeSource
    try {
      const res = await fetch(`${API}/persons/${sourceId}/merge/${targetId}`, { method: 'POST' })
      if (res.ok) {
        // Optimistically merge cached photo lists so the target's avatar
        // remains visible immediately instead of falling back to the default.
        setPhotos(prev => {
          const next = { ...prev }
          const srcPhotos = Array.isArray(next[sourceId]) ? next[sourceId] : []
          const tgtPhotos = Array.isArray(next[targetId]) ? next[targetId] : []
          const existingIds = new Set(tgtPhotos.map(p => p.id))
          const merged = [
            ...tgtPhotos,
            ...srcPhotos.filter(p => !existingIds.has(p.id)),
          ]
          next[targetId] = merged
          delete next[sourceId]
          return next
        })

        // If the source was expanded, collapse it because it will be removed.
        if (expandedId === sourceId) setExpandedId(null)

        setMergeSource(null)
        await fetchPersons()
      }
    } catch (e) { console.error(e) }
  }

  const cancelMerge = () => setMergeSource(null)

  return (
    <section className="pm-root">
      <div className="pm-header">
        <h2 className="pm-title">People</h2>
        {mergeSource && (
          <div className="pm-merge-banner">
            <span>
              Merging <strong>{persons.find(p => p.id === mergeSource)?.name}</strong> →
              click another person to merge into them
            </span>
            <button className="pm-btn pm-btn-ghost" onClick={cancelMerge}>Cancel</button>
          </div>
        )}
      </div>

      {persons.length === 0 && (
        <p className="pm-empty">No people detected yet. Run a folder scan to detect faces.</p>
      )}

      <div
        ref={personGridRef}
        className={`pm-grid ${isDragging ? 'pm-grid--dragging' : ''}`}
        onPointerDown={handleGridPointerDown}
        onPointerMove={handleGridPointerMove}
        onPointerUp={stopGridDrag}
        onPointerCancel={stopGridDrag}
        onPointerLeave={stopGridDrag}
      >
        {persons.map(person => {
          const isSource = mergeSource === person.id
          const isExpanded = expandedId === person.id
          const personPhotos = photos[person.id] || []

          return (
            <div
              key={person.id}
              className={`pm-card ${isSource ? 'pm-card--source' : ''} ${mergeSource && !isSource ? 'pm-card--merge-target' : ''}`}
            >
              {/* Avatar */}
              <div className="pm-avatar">
                {personPhotos[0]
                  ? <img src={`${API}/${personPhotos[0].id}/content`} alt={person.name} className="pm-avatar-img" />
                  : <span className="pm-avatar-icon">👤</span>
                }
              </div>

              {/* Name / edit */}
              {editingId === person.id ? (
                <div className="pm-edit">
                  <input
                    ref={inputRef}
                    className="pm-input"
                    value={editName}
                    onChange={e => setEditName(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') saveName(person.id)
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                  />
                  <div className="pm-edit-actions">
                    <button className="pm-btn pm-btn-primary" onClick={() => saveName(person.id)}>Save</button>
                    <button className="pm-btn pm-btn-ghost" onClick={() => setEditingId(null)}>Cancel</button>
                  </div>
                </div>
              ) : (
                <div className="pm-name-row">
                  <span className="pm-name">{person.name}</span>
                  <button
                    className="pm-icon-btn"
                    title="Rename"
                    onClick={() => { setEditingId(person.id); setEditName(person.name) }}
                  >✏️</button>
                </div>
              )}

              {/* Action row */}
              <div className="pm-actions">
                <button
                  className="pm-btn pm-btn-sm"
                  onClick={() => fetchPhotos(person.id)}
                  disabled={loadingPhotos[person.id]}
                >
                  {loadingPhotos[person.id] ? '…' : isExpanded ? 'Hide photos' : 'See photos'}
                </button>

                {mergeSource && !isSource ? (
                  <button className="pm-btn pm-btn-sm pm-btn-merge" onClick={() => confirmMerge(person.id)}>
                    ← Merge into
                  </button>
                ) : !mergeSource ? (
                  <button className="pm-btn pm-btn-sm pm-btn-ghost" onClick={() => startMerge(person.id)}>
                    🔗 Merge
                  </button>
                ) : null}
              </div>

              {/* Inline photo strip */}
              {isExpanded && (
                <div className="pm-strip">
                  {personPhotos.length === 0
                    ? <span className="pm-strip-empty">No photos found</span>
                    : personPhotos.slice(0, 8).map(photo => (
                        <img
                          key={photo.id}
                          src={`${API}/${photo.id}/content`}
                          alt=""
                          className="pm-strip-thumb"
                          title={photo.path.split(/[\\/]/).pop()}
                        />
                      ))
                  }
                  {personPhotos.length > 8 && (
                    <span className="pm-strip-more">+{personPhotos.length - 8} more</span>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}