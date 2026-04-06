import { useState, useEffect, useRef } from 'react'
import '../styles/PhotoCard.css'

const API = 'http://localhost:8000/files'

function PhotoCard({ photo, onPersonTagCleared, cardRef }) {
  const [imageError, setImageError] = useState(false)
  const [videoError, setVideoError] = useState(false)

  // Person Tagging State
  const [personsList, setPersonsList] = useState([])
  const [loadingPersons, setLoadingPersons] = useState(false)
  const [selectedPersonForAdd, setSelectedPersonForAdd] = useState('')
  const [customPersonLabel, setCustomPersonLabel] = useState('')

  // Video Playback State
  const [isPlaying, setIsPlaying] = useState(false)
  const [showPlayOverlay, setShowPlayOverlay] = useState(true)

  // Refs
  const dialogRef = useRef(null)
  const cardVideoRef = useRef(null)
  const modalVideoRef = useRef(null)

  // --- Effects ---

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return

    const handleClick = (e) => {
      if (e.target === dialog) closeModal()
    }
    const handleCancel = (e) => {
      e.preventDefault()
      closeModal()
    }

    dialog.addEventListener('click', handleClick)
    dialog.addEventListener('cancel', handleCancel)
    return () => {
      dialog.removeEventListener('click', handleClick)
      dialog.removeEventListener('cancel', handleCancel)
    }
  }, [])

  useEffect(() => {
    const cardVideo = cardVideoRef.current
    const modalVideo = modalVideoRef.current
    const resetVideo = (v) => { if (v) { v.pause(); v.currentTime = 0 } }
    return () => {
      resetVideo(cardVideo)
      resetVideo(modalVideo)
      setIsPlaying(false)
      setShowPlayOverlay(true)
    }
  }, [])

  useEffect(() => {
    const handleFullscreenChange = () => {
      if (!document.fullscreenElement) document.body.classList.remove('video-fullscreen')
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  // --- Utility ---

  const getFileExtension = (path) => path.split('.').pop().toLowerCase()
  const isImageFile = () => ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'].includes(getFileExtension(photo.path))
  const isVideoFile = () => ['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(getFileExtension(photo.path))

  const getContrastColor = (hexColor) => {
    if (!hexColor) return '#111'
    const cleaned = hexColor.replace('#', '')
    const bigint = parseInt(
      cleaned.length === 3 ? cleaned.split('').map(c => c + c).join('') : cleaned, 16
    )
    const r = (bigint >> 16) & 255
    const g = (bigint >> 8) & 255
    const b = bigint & 255
    return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? '#111' : '#fff'
  }

  const getImageUrl = () => `${API}/${photo.id}/content`
  const getFileName = () => photo.path.split('\\').pop() || photo.path.split('/').pop()

  const formatDate = (dateStr) =>
    new Date(dateStr).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })

  const formatDateTime = (dateStr) =>
    new Date(dateStr).toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    })

  // --- Handlers ---

  const handleClearPersonTag = async (personId, event) => {
    event.stopPropagation()
    try {
      const response = await fetch(`${API}/${photo.id}/persons/${personId}`, { method: 'DELETE' })
      if (!response.ok) {
        const err = await response.json().catch(() => null)
        throw new Error(err?.detail || 'Unable to clear person tag')
      }
      onPersonTagCleared?.()
    } catch (err) {
      console.error('Error clearing person tag:', err)
    }
  }

  const addLabelFromDropdown = async (event) => {
    event.stopPropagation()
    if (!selectedPersonForAdd) return
    if (selectedPersonForAdd === 'other' && !customPersonLabel.trim()) return
    try {
      const body = selectedPersonForAdd === 'other'
        ? { person_name: customPersonLabel.trim() }
        : { person_id: Number(selectedPersonForAdd) }
      const response = await fetch(`${API}/${photo.id}/persons`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => null)
        throw new Error(err?.detail || 'Unable to add label')
      }
      setSelectedPersonForAdd('')
      setCustomPersonLabel('')
      onPersonTagCleared?.()
    } catch (err) {
      console.error('Error adding label:', err)
    }
  }

  const handleCardVideoClick = (e) => {
    e.stopPropagation()
    if (cardVideoRef.current) {
      cardVideoRef.current.paused
        ? cardVideoRef.current.play().catch(console.error)
        : cardVideoRef.current.pause()
    }
  }

  const openModal = () => {
    if (dialogRef.current) {
      dialogRef.current.showModal()
      if (personsList.length === 0 && !loadingPersons) {
        setLoadingPersons(true)
        fetch(`${API}/persons`)
          .then(res => res.ok ? res.json() : [])
          .then(data => setPersonsList(Array.isArray(data) ? data : []))
          .catch(console.error)
          .finally(() => setLoadingPersons(false))
      }
    }
  }

  const closeModal = () => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (modalVideoRef.current) {
      modalVideoRef.current.pause()
      modalVideoRef.current.currentTime = 0
    }
    dialog.classList.add('closing')
    setTimeout(() => {
      dialog.classList.remove('closing')
      dialog.close()
    }, 280)
  }

  // --- Render ---

  const renderCardMedia = () => {
    if (isVideoFile()) {
      if (videoError) {
        return (
          <div className="no-image-placeholder">
            <span className="file-icon">🎬</span>
            <span className="file-name">{getFileName()}</span>
          </div>
        )
      }
      return (
        <div className={`video-container ${isPlaying ? 'playing' : ''}`} onClick={handleCardVideoClick}>
          <video
            ref={cardVideoRef}
            src={getImageUrl()}
            className="photo-image"
            muted
            playsInline
            preload="metadata"
            onError={() => setVideoError(true)}
            onEnded={() => { setIsPlaying(false); setShowPlayOverlay(true); if (cardVideoRef.current) cardVideoRef.current.currentTime = 0 }}
            onPlay={() => { setIsPlaying(true); setShowPlayOverlay(false) }}
            onPause={() => { setIsPlaying(false); setShowPlayOverlay(true) }}
          />
          {showPlayOverlay && !isPlaying && (
            <div className="video-play-overlay">
              <div className="play-icon">▶</div>
            </div>
          )}
        </div>
      )
    }
    if (!imageError && isImageFile()) {
      return (
        <img
          src={getImageUrl()}
          alt={getFileName()}
          onError={() => setImageError(true)}
          className="photo-image"
        />
      )
    }
    return (
      <div className="no-image-placeholder">
        <span className="file-icon">🖼️</span>
        <span className="file-name">{getFileName()}</span>
      </div>
    )
  }

  const renderModalMedia = () => {
    if (isVideoFile()) {
      if (videoError) {
        return (
          <div className="no-image-placeholder-large">
            <span className="file-icon-large">🎬</span>
            <p>Video cannot be played</p>
            <p className="file-path">{photo.path}</p>
          </div>
        )
      }
      return (
        <div className="modal-video-wrapper">
          <video
            ref={modalVideoRef}
            src={getImageUrl()}
            className="modal-image"
            controls
            preload="metadata"
            onError={() => setVideoError(true)}
            controlsList="nodownload"
            playsInline
          >
            Your browser doesn't support video playback.
          </video>
        </div>
      )
    }
    if (!imageError && isImageFile()) {
      return (
        <img
          src={getImageUrl()}
          alt={getFileName()}
          onError={() => setImageError(true)}
          className="modal-image"
        />
      )
    }
    return (
      <div className="no-image-placeholder-large">
        <span className="file-icon-large">🖼️</span>
        <p>Could not load image</p>
        <p className="file-path">{photo.path}</p>
      </div>
    )
  }

  return (
    <>
      {/* ── Card ── */}
      <div
        className="photo-card"
        ref={cardRef}
        data-photo-id={photo.id}
        onClick={openModal}
      >
        <div className="photo-image-container">
          {renderCardMedia()}
        </div>

        <div className="photo-info">
          <h3 className="photo-name">{getFileName()}</h3>
          <div className="photo-details">
            {photo.category && (
              <span className="detail-badge category">{photo.category}</span>
            )}
            {photo.person_ids && photo.person_ids.length > 0 && (
              <div className="person-tag-row">
                {photo.person_ids.map((personId, idx) => {
                  const name = photo.person_names?.[idx] || `Person ${personId}`
                  const color = photo.person_colors?.[idx] || '#e8f5e9'
                  return (
                    <span
                      key={`${photo.id}-${personId}-${idx}`}
                      className="detail-badge person label-with-remove"
                      onClick={(e) => e.stopPropagation()}
                      style={{ backgroundColor: color, color: getContrastColor(color), borderColor: color }}
                    >
                      {name}
                      <button
                        type="button"
                        className="detail-badge-remove"
                        onClick={(e) => handleClearPersonTag(personId, e)}
                        title={`Remove ${name}`}
                      >✕</button>
                    </span>
                  )
                })}
              </div>
            )}
          </div>
          {photo.scenario && <p className="photo-description">{photo.scenario}</p>}
          <p className="photo-date">{formatDate(photo.created_at)}</p>
        </div>
      </div>

      {/* ── Modal ── */}
      <dialog ref={dialogRef} className="photo-modal">
        <div className="modal-inner" onClick={(e) => e.stopPropagation()}>

          {/* Close button — floats above everything */}
          <button className="modal-close" onClick={closeModal} aria-label="Close">✕</button>

          {/* LEFT — Media */}
          <div className="modal-image-container">
            {renderModalMedia()}
          </div>

          {/* RIGHT — Info panel */}
          <div className="modal-info">
            <div className="modal-info-scroll">

              {/* Header */}
              <div className="modal-header">
                <h2 className="modal-title">{getFileName()}</h2>
                <p className="modal-subtitle">{photo.path}</p>
              </div>

              <div className="modal-divider" />

              {/* Category */}
              <div className="detail-item">
                <span className="label">Category</span>
                <span className="value">{photo.category || '—'}</span>
              </div>

              {/* Description */}
              {photo.scenario && (
                <div className="detail-item">
                  <span className="label">Description</span>
                  <span className="value">{photo.scenario}</span>
                </div>
              )}

              {/* People */}
              <div className="detail-item">
                <span className="label">People</span>
                {photo.person_ids && photo.person_ids.length > 0 ? (
                  <div className="modal-person-tags">
                    {photo.person_ids.map((personId, idx) => {
                      const name = photo.person_names?.[idx] || `Person ${personId}`
                      const color = photo.person_colors?.[idx] || '#e8f5e9'
                      return (
                        <span
                          key={`modal-${photo.id}-${personId}-${idx}`}
                          className="modal-person-badge"
                          style={{ backgroundColor: color, color: getContrastColor(color), borderColor: color }}
                        >
                          {name}
                          <button
                            type="button"
                            className="modal-person-badge-remove"
                            onClick={(e) => handleClearPersonTag(personId, e)}
                            title={`Remove ${name}`}
                          >✕</button>
                        </span>
                      )
                    })}
                  </div>
                ) : (
                  <span className="value" style={{ opacity: 0.5 }}>No people tagged</span>
                )}
              </div>

              <div className="modal-divider" />

              {/* Add label */}
              <div className="detail-item">
                <span className="label">Tag a person</span>
                <div className="add-label-section">
                  <div className="add-label-row">
                    <select
                      value={selectedPersonForAdd}
                      onChange={e => setSelectedPersonForAdd(e.target.value)}
                    >
                      <option value="">{loadingPersons ? 'Loading…' : 'Select person'}</option>
                      {personsList.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                      <option value="other">Other…</option>
                    </select>

                    {selectedPersonForAdd === 'other' && (
                      <input
                        type="text"
                        value={customPersonLabel}
                        onChange={e => setCustomPersonLabel(e.target.value)}
                        placeholder="Enter name…"
                      />
                    )}

                    <button
                      type="button"
                      onClick={addLabelFromDropdown}
                      className="add-label-btn"
                      disabled={
                        !selectedPersonForAdd ||
                        (selectedPersonForAdd === 'other' && !customPersonLabel.trim())
                      }
                    >
                      Add Tag
                    </button>
                  </div>
                </div>
              </div>

            </div>

            {/* Footer */}
            <div className="modal-footer">
              <span className="modal-date">Added {formatDateTime(photo.created_at)}</span>
            </div>
          </div>

        </div>
      </dialog>
    </>
  )
}

export default PhotoCard