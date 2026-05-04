import { useState, useEffect, useRef } from 'react'
import '../styles/PhotoCard.css'
import PhotoModal from './PhotoCard/PhotoModal'

const API = `http://${window.location.hostname}:8000/files`

function PhotoCard({ photo, onPhotoUpdated, cardRef, onRefresh }) {
  const [imageError, setImageError] = useState(false)
  const [videoError, setVideoError] = useState(false)
  const [personsList, setPersonsList] = useState([])
  const [loadingPersons, setLoadingPersons] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [showPlayOverlay, setShowPlayOverlay] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)

  const cardVideoRef = useRef(null)

  const getFileExtension = (path) => path.split('.').pop().toLowerCase()
  const isImageFile = () => ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'].includes(getFileExtension(photo.path))
  const isVideoFile = () => ['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(getFileExtension(photo.path))
  
  const getImageUrl = () => `${API}/${photo.id}/content${photo._cacheBuster ? `?t=${photo._cacheBuster}` : ''}`
  const getThumbnailUrl = () => `${API}/${photo.id}/thumbnail${photo._cacheBuster ? `?t=${photo._cacheBuster}` : ''}`
  const getFileName = () => photo.path.split(/[\\/]/).pop()
  
  const formatDate = (dateStr) => new Date(dateStr).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
  const formatDateTime = (dateStr) => new Date(dateStr).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

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
        onPhotoUpdated?.(updated)
        return updated
      }
    } catch (err) { console.error(err) }
  }

  return (
    <>
      <div className="photo-card" ref={cardRef} data-photo-id={photo.id} onClick={() => setIsModalOpen(true)}>
        <div className="photo-image-container">
          {isVideoFile() ? (
            <div className={`video-container ${isPlaying ? 'playing' : ''}`} onClick={(e) => { e.stopPropagation(); setIsPlaying(!isPlaying); }}>
              <video ref={cardVideoRef} src={isPlaying ? getImageUrl() : null} poster={getThumbnailUrl()} className="photo-image" muted playsInline loop autoPlay={isPlaying} onPlay={() => setShowPlayOverlay(false)} onPause={() => setShowPlayOverlay(true)} />
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
            <img src={getThumbnailUrl()} alt={getFileName()} loading="lazy" className="photo-image" onError={() => setImageError(true)} />
          )}
        </div>
        <div className="photo-info">
          <h3 className="photo-name">{getFileName()}</h3>
          <div className="photo-details">
            {photo.category && <span className="detail-badge category">{photo.category}</span>}
            <div className="person-tag-row">
              {photo.person_ids?.map((id, i) => (
                <span key={id} className="detail-badge person" style={{ backgroundColor: photo.person_colors?.[i], color: getContrastColor(photo.person_colors?.[i]) }}>
                  {photo.person_names?.[i] || `Person ${id}`}
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
          photo={photo}
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          onPhotoUpdated={onPhotoUpdated}
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