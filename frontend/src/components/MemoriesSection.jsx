import { useState, useEffect, useRef, useCallback } from 'react'
import '../styles/MemoriesSection.css'
import PersonManager from './PersonManager'
import { BASE_URL } from '../api'

const MEMORY_ICONS = {
  location: '📍',
  album: '📁',
  time: '📅',
}

function MemoryCard({ memory, onClick, isActive }) {
  const previews = memory.preview_ids
    ? memory.preview_ids.split(',')
    : memory.cover_file_id
    ? [memory.cover_file_id.toString()]
    : []

  const [currentIndex, setCurrentIndex] = useState(0)

  useEffect(() => {
    if (previews.length <= 1) return
    const interval = setInterval(() => {
      setCurrentIndex(prev => (prev + 1) % previews.length)
    }, 4000 + Math.random() * 2000) // Staggered 4-6s
    return () => clearInterval(interval)
  }, [previews.length])

  return (
    <div
      className={`ms-memory-card ${isActive ? 'ms-memory-card--active' : ''}`}
      onClick={() => onClick(memory)}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onClick(memory)}
    >
      <div className="ms-memory-thumb">
        {previews.length > 0 ? (
          previews.map((fileId, idx) => (
            <img
              key={fileId}
              src={`${BASE_URL}/files/${fileId}/thumbnail`}
              alt={`${memory.title} ${idx}`}
              className={`ms-memory-thumb-img ${idx === currentIndex ? 'active' : ''}`}
              loading="lazy"
              style={{
                opacity: idx === currentIndex ? 1 : 0,
              }}
            />
          ))
        ) : (
          <div className="ms-memory-thumb-placeholder">
            {MEMORY_ICONS[memory.memory_type] || '🖼️'}
          </div>
        )}
        <div className="ms-memory-gradient" />
        <div className="ms-memory-meta">
          <div className="ms-memory-type-badge">
            {MEMORY_ICONS[memory.memory_type] || '🖼️'}
          </div>
        </div>
      </div>
      <div className="ms-memory-info">
        <div className="ms-memory-title" title={memory.title}>{memory.title}</div>
        {memory.subtitle && (
          <div className="ms-memory-subtitle">{memory.subtitle}</div>
        )}
        <div className="ms-memory-count">{memory.photo_count} photos</div>
      </div>
    </div>
  )
}

export default function MemoriesSection({
  onPersonsChange,
  onPhotoClick,
  onPersonPhotoClick,
  refreshKey,
  onMemorySelect,
}) {
  const [activeTab, setActiveTab] = useState('memories')
  const [memories, setMemories] = useState([])
  const [memoriesLoading, setMemoriesLoading] = useState(false)
  const [activeMemoryId, setActiveMemoryId] = useState(null)
  const [isGenerating, setIsGenerating] = useState(false)

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

  const fetchMemories = useCallback(async (silent = false) => {
    if (!silent) setMemoriesLoading(true)
    try {
      const res = await fetch(`${BASE_URL}/memories/`)
      if (res.ok) {
        const data = await res.json()
        setMemories(data || [])
      }
    } catch (err) {
      console.error('Failed to fetch memories:', err)
    } finally {
      if (!silent) setMemoriesLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMemories(refreshKey > 0)
  }, [fetchMemories, refreshKey])

  const handleMemoryClick = (memory) => {
    if (activeMemoryId === memory.id) {
      // Deselect — show all photos
      setActiveMemoryId(null)
      onMemorySelect?.(null)
    } else {
      setActiveMemoryId(memory.id)
      onMemorySelect?.(memory)
    }
  }

  const handleGenerate = async () => {
    setIsGenerating(true)
    try {
      await fetch(`${BASE_URL}/memories/generate`, { method: 'POST' })
      setTimeout(() => {
        fetchMemories()
        setIsGenerating(false)
      }, 3000)
    } catch (err) {
      console.error('Failed to trigger generation:', err)
      setIsGenerating(false)
    }
  }

  // ── Scroll / momentum logic (same pattern as PersonManager) ─────────────────
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
      if (Math.abs(velocity) < 0.01) { stopMomentum(); return }
      const nextScroll = gridEl.scrollLeft + velocity * delta
      const maxScroll = gridEl.scrollWidth - gridEl.clientWidth
      if (nextScroll <= 0 || nextScroll >= maxScroll) { stopMomentum(); return }
      gridEl.scrollLeft = nextScroll
      velocityRef.current = velocity * Math.pow(0.92, delta / 16)
      momentumFrameRef.current = requestAnimationFrame(step)
    }
    momentumFrameRef.current = requestAnimationFrame(step)
  }

  const handlePointerDown = (e) => {
    if (e.button !== 0 || e.target.closest('button, input, img')) return
    const grid = gridRef.current
    if (!grid) return
    stopMomentum()
    isDragging.current = true
    startX.current = e.clientX
    scrollLeft.current = gridRef.current?.scrollLeft || 0
    pointerHistoryRef.current = [{ x: e.clientX, time: performance.now() }]
    velocityRef.current = 0
    stopMomentum()
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
    if (Math.abs(velocityRef.current) > 0.05) startMomentum()
    pointerHistoryRef.current = []
  }

  useEffect(() => {
    const root = rootRef.current
    const grid = gridRef.current
    if (!root || !grid) return
    const handleWheel = (e) => {
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return // let horizontal scrolling work naturally
      stopMomentum()
      e.preventDefault()
      const delta = e.deltaY || e.detail || e.wheelDelta
      grid.scrollLeft += delta * 1.5
    }
    root.addEventListener('wheel', handleWheel, { passive: false })
    return () => root.removeEventListener('wheel', handleWheel)
  }, [memories])

  return (
    <div className="ms-root">
      {/* ── Tab Bar ── */}
      <div className="ms-tab-bar">
        <button
          id="ms-tab-memories"
          className={`ms-tab ${activeTab === 'memories' ? 'ms-tab--active' : ''}`}
          onClick={() => setActiveTab('memories')}
        >
          <span className="ms-tab-icon">✨</span>
          Memories
        </button>
        <button
          id="ms-tab-people"
          className={`ms-tab ${activeTab === 'people' ? 'ms-tab--active' : ''}`}
          onClick={() => { setActiveTab('people'); setActiveMemoryId(null); onMemorySelect?.(null) }}
        >
          <span className="ms-tab-icon">👥</span>
          People
        </button>

        {activeTab === 'memories' && (
          <div className="ms-tab-actions">
            {activeMemoryId && (
              <button
                className="ms-clear-btn"
                onClick={() => { setActiveMemoryId(null); onMemorySelect?.(null) }}
                title="Show all photos"
              >
                ✕ Clear Filter
              </button>
            )}
            <button
              className="ms-generate-btn"
              onClick={handleGenerate}
              disabled={isGenerating}
              title="Regenerate memories"
            >
              {isGenerating ? '⟳ Generating…' : '⟳ Refresh'}
            </button>
          </div>
        )}
      </div>

      {/* ── Memories Tab ── */}
      {activeTab === 'memories' && (
        <div className="ms-memories-panel" ref={rootRef}>
          {memoriesLoading ? (
            <div className="ms-loading">
              <div className="ms-spinner" />
              <span>Loading memories…</span>
            </div>
          ) : memories.length === 0 ? (
            <div className="ms-empty">
              <div className="ms-empty-icon">✨</div>
              <p>No memories yet.</p>
              <p className="ms-empty-sub">
                Run a scan or click Refresh to generate memories from your photos.
              </p>
            </div>
          ) : (
            <div
              className="ms-memory-grid"
              ref={gridRef}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerUp}
            >
              {memories.map(memory => (
                <MemoryCard
                  key={memory.id}
                  memory={memory}
                  onClick={handleMemoryClick}
                  isActive={activeMemoryId === memory.id}
                />
              ))}
            </div>
          )}

          {activeMemoryId && !memoriesLoading && (
            <div className="ms-active-label">
              Showing photos from: <strong>{memories.find(m => m.id === activeMemoryId)?.title}</strong>
            </div>
          )}
        </div>
      )}

      {/* ── People Tab ── */}
      {activeTab === 'people' && (
        <PersonManager
          onPersonsChange={onPersonsChange}
          onPhotoClick={onPhotoClick}
          onPersonPhotoClick={onPersonPhotoClick}
          refreshKey={refreshKey}
        />
      )}
    </div>
  )
}
