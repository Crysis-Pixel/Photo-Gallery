import { useState, useEffect, useRef } from 'react'
import '../styles/PhotoCard.css'

const API = 'http://localhost:8000/files'

function PhotoCard({ photo, onPhotoUpdated, cardRef }) {
  const [imageError, setImageError] = useState(false)
  const [videoError, setVideoError] = useState(false)

  // Person Tagging State
  const [personsList, setPersonsList] = useState([])
  const [loadingPersons, setLoadingPersons] = useState(false)
  const [selectedPersonForAdd, setSelectedPersonForAdd] = useState('')
  const [customPersonLabel, setCustomPersonLabel] = useState('')
  const [selectedFace, setSelectedFace] = useState(null)
  const [imgAspectRatio, setImgAspectRatio] = useState('auto')
  const [isRescanning, setIsRescanning] = useState(false)

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
  const getThumbnailUrl = () => `${API}/${photo.id}/thumbnail`
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
      const updatedPhoto = await response.json()
      onPhotoUpdated?.(updatedPhoto)
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
      let response;
      if (selectedFace) {
        response = await fetch(`${API}/faces/${selectedFace.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
      } else {
        response = await fetch(`${API}/${photo.id}/persons`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
      }
      if (!response.ok) {
        const err = await response.json().catch(() => null)
        throw new Error(err?.detail || 'Unable to add label')
      }
      const updatedPhoto = await response.json()
      setSelectedPersonForAdd('')
      setCustomPersonLabel('')
      setSelectedFace(null)
      onPhotoUpdated?.(updatedPhoto)
    } catch (err) {
      console.error('Error adding label:', err)
    }
  }

  const handleRescan = async (event) => {
    event.stopPropagation()
    setIsRescanning(true)
    try {
      // Invalidate cached thumbnail so it regenerates after rescan
      await fetch(`${API}/${photo.id}/thumbnail`, { method: 'DELETE' }).catch(() => {})
      const response = await fetch(`${API}/${photo.id}/rescan`, { method: 'POST' })
      if (!response.ok) throw new Error('Rescan failed')
      const updatedPhoto = await response.json()
      onPhotoUpdated?.(updatedPhoto)
    } catch (err) {
      console.error('Error rescanning:', err)
    } finally {
      setIsRescanning(false)
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
    setSelectedFace(null)
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
            poster={getThumbnailUrl()}
            className="photo-image"
            muted
            playsInline
            preload="none"
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
          src={getThumbnailUrl()}
          alt={getFileName()}
          loading="lazy"
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
        <div className="modal-image-wrapper" style={{ aspectRatio: imgAspectRatio }}>
          <img
            src={getImageUrl()}
            alt={getFileName()}
            onLoad={(e) => {
              const { naturalWidth, naturalHeight } = e.target;
              if (naturalWidth && naturalHeight) {
                setImgAspectRatio(`${naturalWidth} / ${naturalHeight}`);
              }
            }}
            onError={() => setImageError(true)}
            className="modal-image"
          />
          {photo.faces && photo.faces.map(face => {
            if (face.box_left == null) return null;
            return (
              <div
                key={face.id}
                className={`face-box ${selectedFace?.id === face.id ? 'active' : ''}`}
                style={{
                  left: `${face.box_left * 100}%`,
                  top: `${face.box_top * 100}%`,
                  width: `${face.box_width * 100}%`,
                  height: `${face.box_height * 100}%`,
                  borderColor: face.person_color || '#e8f5e9'
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedFace(selectedFace?.id === face.id ? null : face);
                }}
              >
                <span className="face-box-label" style={{ backgroundColor: face.person_color || '#e8f5e9', color: getContrastColor(face.person_color || '#e8f5e9') }}>
                  {face.person_name || `Person ${face.person_id}`}
                </span>
              </div>
            )
          })}
        </div>
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
                <span className="label">
                  {selectedFace ? `Relabel Target Face` : 'Tag a person'}
                </span>
                {selectedFace && (
                  <div style={{ fontSize: '0.8rem', color: 'var(--accent)', marginBottom: '0.4rem', background: 'rgba(232, 213, 176, 0.1)', padding: '0.3rem 0.6rem', borderRadius: '4px' }}>
                    Updating: {selectedFace.person_name || `Person ${selectedFace.person_id}`}
                  </div>
                )}
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
                      {selectedFace ? 'Update Face Tag' : 'Add Tag'}
                    </button>
                    {selectedFace && (
                      <button type="button" onClick={() => setSelectedFace(null)} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '0.75rem', cursor: 'pointer', textAlign: 'center' }}>Cancel face selection</button>
                    )}
                  </div>
                </div>
              </div>

            </div>

            {/* Footer */}
            <div className="modal-footer">
              <span className="modal-date">Added {formatDateTime(photo.created_at)}</span>
              <button 
                type="button" 
                onClick={handleRescan}
                className="add-label-btn" 
                style={{ width: 'auto', padding: '0.4rem 0.8rem', fontSize: '0.75rem', marginLeft: 'auto' }}
                disabled={isRescanning}
              >
                {isRescanning ? 'Scanning...' : 'Rescan Picture'}
              </button>
            </div>
          </div>

        </div>
      </dialog>
    </>
  )
}

export default PhotoCard