import { useState, useRef } from 'react'
import '../styles/PhotoCard.css'
import PhotoModal from './PhotoCard/PhotoModal'
import { FILES_API as API } from '../api'

function PhotoCard({ photo: photoProp, onPhotoUpdated, cardRef, onRefresh }) {
  // Keep a local copy so the card reflects edits made inside the modal
  // immediately on close, without waiting for a server refetch.
  const [localPhoto, setLocalPhoto] = useState(photoProp)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [showPlayOverlay, setShowPlayOverlay] = useState(true)
  const [imageError, setImageError] = useState(false)

  const cardVideoRef = useRef(null)

  // When the parent grid updates the photo (e.g. from its own silent refresh),
  // only accept it if the modal is closed — otherwise the modal's version wins.
  const photo = isModalOpen ? localPhoto : photoProp

  const getFileExtension = (path) => path.split('.').pop().toLowerCase()
  const isImageFile = () => ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'].includes(getFileExtension(photo.path))
  const isVideoFile = () => ['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(getFileExtension(photo.path))

  const getImageUrl = () => `${API}/${photo.id}/content${photo._cacheBuster ? `?t=${photo._cacheBuster}` : ''}`
  const getThumbnailUrl = () => `${API}/${photo.id}/thumbnail${photo._cacheBuster ? `?t=${photo._cacheBuster}` : ''}`
  const getFileName = () => photo.path.split(/[\\/]/).pop()

  const formatDate = (dateStr) => new Date(dateStr).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
  const formatDateTime = (dateStr) => new Date(dateStr).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

  const [personsList, setPersonsList] = useState([])
  const [loadingPersons, setLoadingPersons] = useState(false)

  const fetchPersons = async () => {
    setLoadingPersons(true)
    try {
      const res = await fetch(`${API}/persons`)
      const data = await res.json()
      setPersonsList(data)
    } catch (err) { console.error(err) }
    finally { setLoadingPersons(false) }
  }

  const getSortedPersons = () => {
    return [...personsList].sort((a, b) => {
      const aIsUnnamed = a.name.startsWith('Person ');
      const bIsUnnamed = b.name.startsWith('Person ');
      if (aIsUnnamed && !bIsUnnamed) return 1;
      if (!aIsUnnamed && bIsUnnamed) return -1;
      return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
    });
  }

  const getContrastColor = (hexColor) => {
    if (!hexColor) return '#111'
    const cleaned = hexColor.replace('#', '')
    const bigint = parseInt(cleaned.length === 3 ? cleaned.split('').map(c => c + c).join('') : cleaned, 16)
    const r = (bigint >> 16) & 255, g = (bigint >> 8) & 255, b = bigint & 255
    return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? '#111' : '#fff'
  }

  const handleClearPersonTag = async (personId, event) => {
    event.stopPropagation()
    try {
      const res = await fetch(`${API}/${photo.id}/persons/${personId}`, { method: 'DELETE' })
      if (res.ok) {
        const updated = await res.json()
        return updated
      }
    } catch (err) { console.error(err) }
  }

  // Called by the modal whenever the photo changes (tag added/removed, rescan, etc.)
  // Updates both the local card state and notifies the parent grid.
  const handlePhotoUpdatedInModal = (updated) => {
    setLocalPhoto(updated)
    onPhotoUpdated?.(updated)
  }

  // When the modal closes, whatever localPhoto holds is the truth — push it
  // to the parent so the grid card stays in sync without any server fetch.
  const handleModalClose = () => {
    setIsModalOpen(false)
    onPhotoUpdated?.(localPhoto)
  }

  // Derive person tags from faces when available (most accurate after rescan),
  // otherwise fall back to the denormalized top-level arrays.
  const personTags = (() => {
    const src = photo
    if (src.faces && src.faces.length > 0) {
      const seen = new Set()
      return src.faces
        .filter(f => f.person_id != null)
        .filter(f => { if (seen.has(f.person_id)) return false; seen.add(f.person_id); return true })
        .map(f => ({ personId: f.person_id, name: f.person_name || `Person ${f.person_id}`, color: f.person_color || null }))
    }
    const seen = new Set()
    return (src.person_ids || [])
      .map((id, i) => ({ personId: id, name: src.person_names?.[i] || `Person ${id}`, color: src.person_colors?.[i] || null }))
      .filter(t => { if (seen.has(t.personId)) return false; seen.add(t.personId); return true })
  })()

  return (
    <>
      <div className="photo-card" ref={cardRef} data-photo-id={photo.id} onClick={() => setIsModalOpen(true)}>
        <div className="photo-image-container">
          {isVideoFile() ? (
            <div className={`video-container ${isPlaying ? 'playing' : ''}`} onClick={(e) => { e.stopPropagation(); setIsPlaying(!isPlaying); }}>
              <video
                ref={cardVideoRef}
                src={isPlaying ? getImageUrl() : null}
                poster={getThumbnailUrl()}
                className="photo-image"
                muted playsInline loop autoPlay={isPlaying}
                onPlay={() => setShowPlayOverlay(false)}
                onPause={() => setShowPlayOverlay(true)}
              />
              {showPlayOverlay && !isPlaying && (
                <div className="video-play-overlay">
                  <div className="play-icon">
                    <svg viewBox="0 0 24 24" fill="currentColor" width="24" height="24">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <img
              src={getThumbnailUrl()}
              alt={getFileName()}
              loading="lazy"
              className="photo-image"
              onError={() => setImageError(true)}
            />
          )}
        </div>
        <div className="photo-info">
          <h3 className="photo-name">{getFileName()}</h3>
          <div className="photo-details">
            {photo.category && <span className="detail-badge category">{photo.category}</span>}
            <div className="person-tag-row">
              {personTags.map(({ personId, name, color }) => (
                <span
                  key={personId}
                  className="detail-badge person"
                  style={{ backgroundColor: color, color: getContrastColor(color) }}
                >
                  {name}
                </span>
              ))}
            </div>
          </div>
          {photo.scenario && <p className="photo-description">{photo.scenario}</p>}
          <p className="photo-date">{formatDate(photo.created_at)}</p>
        </div>
      </div>

      {isModalOpen && (
        <PhotoModal
          photo={localPhoto}
          isOpen={isModalOpen}
          onClose={handleModalClose}
          onPhotoUpdated={handlePhotoUpdatedInModal}
          onRefresh={onRefresh}
          fetchPersons={fetchPersons}
          getSortedPersons={getSortedPersons}
          getContrastColor={getContrastColor}
          formatDateTime={formatDateTime}
          isVideoFile={isVideoFile}
          isImageFile={isImageFile}
          getImageUrl={getImageUrl}
          getFileName={getFileName}
          handleClearPersonTag={handleClearPersonTag}
        />
      )}
    </>
  )
}

export default PhotoCard