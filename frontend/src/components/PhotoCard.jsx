import { useState, useEffect } from 'react'
import '../styles/PhotoCard.css'

function PhotoCard({ photo, onPersonTagCleared }) {
  const [imageError, setImageError] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [personLabelInput, setPersonLabelInput] = useState(photo.person_name || '')

  useEffect(() => {
    if (isModalOpen) {
      setPersonLabelInput(photo.person_name || '')
    }
  }, [isModalOpen, photo.person_name])

  const getFileExtension = (path) => {
    return path.split('.').pop().toLowerCase()
  }

  const isImageFile = () => {
    const ext = getFileExtension(photo.path)
    return ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'].includes(ext)
  }

  const handleImageError = () => {
    setImageError(true)
  }

  const getContrastColor = (hexColor) => {
    if (!hexColor) return '#111'
    const cleaned = hexColor.replace('#', '')
    const bigint = parseInt(cleaned.length === 3 ? cleaned.split('').map(c => c + c).join('') : cleaned, 16)
    const r = (bigint >> 16) & 255
    const g = (bigint >> 8) & 255
    const b = bigint & 255
    const brightness = (r * 299 + g * 587 + b * 114) / 1000
    return brightness > 150 ? '#111' : '#fff'
  }

  const handleClearPersonTag = async (personId, event) => {
    event.stopPropagation()
    try {
      const response = await fetch(`http://localhost:8000/files/${photo.id}/persons/${personId}`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        const errorBody = await response.json().catch(() => null)
        throw new Error(errorBody?.detail || 'Unable to clear person tag')
      }
      onPersonTagCleared?.()
    } catch (err) {
      console.error('Error clearing person tag:', err)
    }
  }

  const savePersonLabel = async (event) => {
    event.stopPropagation()
    if (!personLabelInput.trim()) {
      return
    }

    try {
      const response = await fetch(`http://localhost:8000/files/${photo.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ person_name: personLabelInput.trim() }),
      })
      if (!response.ok) {
        const errorBody = await response.json().catch(() => null)
        throw new Error(errorBody?.detail || 'Unable to save person label')
      }
      onPersonTagCleared?.()
    } catch (err) {
      console.error('Error saving person label:', err)
    }
  }

  const getImageUrl = () => {
    return `http://localhost:8000/files/${photo.id}/content`
  }

  const getFileName = () => {
    return photo.path.split('\\').pop() || photo.path.split('/').pop()
  }

  return (
    <>
      <div className="photo-card" onClick={() => setIsModalOpen(true)}>
        <div className="photo-image-container">
          {!imageError && isImageFile() ? (
            <img
              src={getImageUrl()}
              alt={getFileName()}
              onError={handleImageError}
              className="photo-image"
            />
          ) : (
            <div className="no-image-placeholder">
              <span className="file-icon">🖼️</span>
              <span className="file-name">{getFileName()}</span>
            </div>
          )}
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
                      style={{
                        backgroundColor: color,
                        color: getContrastColor(color),
                        borderColor: color,
                      }}
                    >
                      {name}
                      <button
                        type="button"
                        className="detail-badge-remove"
                        onClick={(e) => handleClearPersonTag(personId, e)}
                        title={`Remove ${name}`}
                      >
                        ✕
                      </button>
                    </span>
                  )
                })}
              </div>
            )}
          </div>
          {photo.scenario && (
            <p className="photo-description">{photo.scenario}</p>
          )}
          <p className="photo-date">
            {new Date(photo.created_at).toLocaleDateString()}
          </p>
        </div>
      </div>

      {isModalOpen && (
        <div className="modal" onClick={() => setIsModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setIsModalOpen(false)}>✕</button>
            <div className="modal-image-container">
              {!imageError && isImageFile() ? (
                <img
                  src={getImageUrl()}
                  alt={getFileName()}
                  onError={handleImageError}
                  className="modal-image"
                />
              ) : (
                <div className="no-image-placeholder-large">
                  <span className="file-icon-large">🖼️</span>
                </div>
              )}
            </div>
            <div className="modal-info">
              <h2>{getFileName()}</h2>
              <p className="file-path">{photo.path}</p>
              <div className="modal-details">
                <div className="detail-item">
                  <span className="label">Category:</span>
                  <span className="value">{photo.category || 'Not tagged'}</span>
                </div>
                {photo.scenario && (
                  <div className="detail-item">
                    <span className="label">Description:</span>
                    <span className="value">{photo.scenario}</span>
                  </div>
                )}
                <div className="detail-item">
                  <span className="label">Person:</span>
                  <span className="value">{(photo.person_names && photo.person_names.length>0) ? photo.person_names.join(', ') : 'No face detected'}</span>
                </div>
                <div className="detail-item">
                  <span className="label">Person label</span>
                  <div className="person-label-edit-row">
                    <input
                      type="text"
                      value={personLabelInput}
                      onChange={e => setPersonLabelInput(e.target.value)}
                      placeholder="Add a label"
                    />
                    <button type="button" onClick={savePersonLabel} className="save-person-label-btn">
                      Save
                    </button>
                  </div>
                </div>
                <div className="detail-item">
                  <span className="label">Added:</span>
                  <span className="value">
                    {new Date(photo.created_at).toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default PhotoCard
