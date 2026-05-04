import { useState, useEffect, useRef, useCallback } from 'react'
import '../styles/PersonManager.css'
import PersonCard from './PersonManager/PersonCard'

const API = `http://${window.location.hostname}:8000/files`

export default function PersonManager({ onPhotoClick, onPersonsChange, refreshKey }) {
  const [persons, setPersons] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadingPhotos, setLoadingPhotos] = useState({})
  const [personPhotos, setPersonPhotos] = useState({})
  const [expandedPerson, setExpandedPerson] = useState(null)
  const [mergeSource, setMergeSource] = useState(null)
  
  const [deleteConfirm, setDeleteConfirm] = useState(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isClosingModal, setIsClosingModal] = useState(false)

  const gridRef = useRef(null)
  const rootRef = useRef(null)
  const isDragging = useRef(false)
  const startX = useRef(0)
  const scrollLeft = useRef(0)
  const pointerHistoryRef = useRef([])
  const velocityRef = useRef(0)
  const momentumFrameRef = useRef(null)
  const momentumLastTimeRef = useRef(0)
  const MOMENTUM_MULTIPLIER = 4

  useEffect(() => {
    fetchPersons()
  }, [refreshKey])

  const fetchPersons = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/persons`)
      const data = await res.json()
      setPersons(data || [])
      onPersonsChange?.(data || [])
    } catch (err) { 
      console.error(err)
      setPersons([])
      onPersonsChange?.([])
    } finally { 
      setLoading(false) 
    }
  }

  const sortedPersons = [...persons].sort((a, b) => {
    const aIsUnnamed = a.name.startsWith('Person ');
    const bIsUnnamed = b.name.startsWith('Person ');
    if (aIsUnnamed && !bIsUnnamed) return 1;
    if (!aIsUnnamed && bIsUnnamed) return -1;
    return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
  });

  const handleRenamed = (updated) => {
    setPersons(prev => prev.map(p => p.id === updated.id ? updated : p))
    if (mergeSource?.id === updated.id) setMergeSource(updated)
  }

  const togglePhotos = async (personId) => {
    if (expandedPerson === personId) {
      setExpandedPerson(null)
      return
    }
    setExpandedPerson(personId)
    if (!personPhotos[personId]) {
      setLoadingPhotos(prev => ({ ...prev, [personId]: true }))
      try {
        const res = await fetch(`${API}/?person_id=${personId}&limit=12`)
        const data = await res.json()
        setPersonPhotos(prev => ({ ...prev, [personId]: data.items }))
      } catch (err) { console.error(err) }
      finally { setLoadingPhotos(prev => ({ ...prev, [personId]: false })) }
    }
  }

  const handleMerge = async (targetId) => {
    if (!mergeSource) return
    const target = persons.find(p => p.id === targetId)
    if (!confirm(`Merge ${mergeSource.name} into ${target?.name}?`)) return
    try {
      const res = await fetch(`${API}/persons/${mergeSource.id}/merge/${targetId}`, { method: 'POST' })
      if (res.ok) {
        setMergeSource(null)
        fetchPersons()
      }
    } catch (err) { console.error(err) }
  }

  const handleDelete = async () => {
    if (!deleteConfirm) return
    setIsDeleting(true)
    try {
      const res = await fetch(`${API}/persons/${deleteConfirm.id}`, { method: 'DELETE' })
      if (res.ok) {
        setPersons(prev => prev.filter(p => p.id !== deleteConfirm.id))
        closeDeleteModal()
      }
    } catch (err) { console.error(err) }
    finally { setIsDeleting(false) }
  }

  const closeDeleteModal = () => {
    setIsClosingModal(true)
    setTimeout(() => {
      setDeleteConfirm(null)
      setIsClosingModal(false)
    }, 280)
  }

  // ── Scrolling Logic ────────────────────────────────────────────────────────

  const stopMomentum = () => {
    if (momentumFrameRef.current) {
      cancelAnimationFrame(momentumFrameRef.current)
      momentumFrameRef.current = null
    }
  }

  const startMomentum = () => {
    const grid = gridRef.current
    if (!grid) return
    stopMomentum()
    momentumLastTimeRef.current = performance.now()

    const step = (timestamp) => {
      const gridEl = gridRef.current
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

  const handlePointerDown = (e) => {
    if (e.button !== 0 || e.target.closest('button, input')) return
    const grid = gridRef.current
    if (!grid) return
    stopMomentum()
    isDragging.current = true
    startX.current = e.clientX
    scrollLeft.current = grid.scrollLeft
    pointerHistoryRef.current = [{ x: e.clientX, time: performance.now() }]
    velocityRef.current = 0
    grid.setPointerCapture?.(e.pointerId)
  }

  const handlePointerMove = (e) => {
    if (!isDragging.current) return
    const grid = gridRef.current
    if (!grid) return
    const walk = e.clientX - startX.current
    grid.scrollLeft = scrollLeft.current - walk

    const now = performance.now()
    const history = pointerHistoryRef.current
    history.push({ x: e.clientX, time: now })
    if (history.length > 10) history.shift()
    
    if (history.length >= 2) {
      const recent = history.slice(-4)
      const first = recent[0], last = recent[recent.length - 1]
      const dt = Math.max(last.time - first.time, 16)
      velocityRef.current = -((last.x - first.x) / dt) * MOMENTUM_MULTIPLIER
    }
  }

  const handlePointerUp = (e) => {
    if (!isDragging.current) return
    isDragging.current = false
    const grid = gridRef.current
    if (grid && e.pointerId) grid.releasePointerCapture?.(e.pointerId)
    if (Math.abs(velocityRef.current) > 0.05) startMomentum()
    pointerHistoryRef.current = []
  }

  useEffect(() => {
    const root = rootRef.current
    const grid = gridRef.current
    if (!root || !grid) return

    const handleWheel = (e) => {
      stopMomentum()
      e.preventDefault()
      let delta = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX
      if (e.deltaMode === 1) delta *= 40
      grid.scrollLeft += delta * 1.5
    }
    root.addEventListener('wheel', handleWheel, { passive: false })
    return () => root.removeEventListener('wheel', handleWheel)
  }, [persons])

  return (
    <div className="pm-root" ref={rootRef}>
      {mergeSource && (
        <div className="pm-merge-banner">
          <span>Merging <strong>{mergeSource.name}</strong>. Select target...</span>
          <button className="pm-btn pm-btn-sm" onClick={() => setMergeSource(null)}>Cancel</button>
        </div>
      )}

      <div 
        className="pm-grid" 
        ref={gridRef} 
        onPointerDown={handlePointerDown} 
        onPointerMove={handlePointerMove} 
        onPointerUp={handlePointerUp} 
        onPointerCancel={handlePointerUp}
      >
        {sortedPersons.map(person => (
          <PersonCard
            key={person.id}
            person={person}
            isSource={mergeSource?.id === person.id}
            mergeSource={mergeSource}
            isExpanded={expandedPerson === person.id}
            loadingPhotos={loadingPhotos}
            onRemove={() => setDeleteConfirm(person)}
            onEdit={(id, name) => {
              const newName = prompt('Rename person:', name)
              if (newName) {
                fetch(`${API}/persons/${id}`, {
                  method: 'PATCH',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ name: newName })
                }).then(res => res.json()).then(handleRenamed)
              }
            }}
            onMerge={(id, isSource) => isSource ? setMergeSource(person) : handleMerge(id)}
            onSeePhotos={togglePhotos}
          >
            {expandedPerson === person.id && (
              <div className="pm-strip">
                {personPhotos[person.id]?.map(photo => (
                  <img key={photo.id} src={`${API}/${photo.id}/thumbnail`} className="pm-strip-thumb pm-strip-thumb--clickable" onClick={() => onPhotoClick?.(photo.id)} />
                ))}
              </div>
            )}
          </PersonCard>
        ))}
      </div>

      {deleteConfirm && (
        <div className={`pm-modal-overlay ${isClosingModal ? 'closing' : ''}`} onClick={closeDeleteModal}>
          <div className="pm-modal" onClick={e => e.stopPropagation()}>
            <div className="pm-modal-icon">⚠️</div>
            <h3 className="pm-modal-title">Delete Person?</h3>
            <p className="pm-modal-message">Remove <strong>{deleteConfirm.name}</strong>? Faces will become untagged.</p>
            <div className="pm-modal-actions">
              <button className="pm-modal-btn pm-modal-btn-cancel" onClick={closeDeleteModal}>Cancel</button>
              <button className="pm-modal-btn pm-modal-btn-delete" onClick={handleDelete} disabled={isDeleting}>{isDeleting ? 'Deleting...' : 'Delete'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}