import { useState, useEffect, useRef } from 'react'
import '../styles/PhotoCard.css'

const API = 'http://localhost:8000/files'

function PhotoCard({ photo, onPersonTagCleared, cardRef }) {
  const [imageError, setImageError] = useState(false)
  const [personsList, setPersonsList] = useState([])
  const [loadingPersons, setLoadingPersons] = useState(false)
  const [selectedPersonForAdd, setSelectedPersonForAdd] = useState('')
  const [customPersonLabel, setCustomPersonLabel] = useState('')
  const dialogRef = useRef(null)
useEffect(() => {
  const dialog = dialogRef.current
  if (!dialog) return

  const handleClick = (e) => {
    if (e.target === dialog) {
      closeModal()
    }
  }

  dialog.addEventListener('click', handleClick)

  return () => dialog.removeEventListener('click', handleClick)
}, [])
  useEffect(() => {
  const dialog = dialogRef.current
  if (!dialog) return

  const handleCancel = (e) => {
    e.preventDefault() // stop instant close
    closeModal()
  }

  dialog.addEventListener('cancel', handleCancel)

  return () => {
    dialog.removeEventListener('cancel', handleCancel)
  }
}, [])

  const getFileExtension = (path) => path.split('.').pop().toLowerCase()

  const isImageFile = () =>
    ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'].includes(getFileExtension(photo.path))

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

  const getImageUrl = () => `${API}/${photo.id}/content`
  const getFileName = () => photo.path.split('\\').pop() || photo.path.split('/').pop()

  const openModal = () => {
    if (dialogRef.current) {
      dialogRef.current.showModal()
      // Fetch persons when modal opens
      setLoadingPersons(true)
      fetch(`${API}/persons`)
        .then(res => res.ok ? res.json() : [])
        .then(data => setPersonsList(Array.isArray(data) ? data : []))
        .catch(err => console.error('Error fetching persons:', err))
        .finally(() => setLoadingPersons(false))
    }
  }

  const closeModal = () => {
    const dialog = dialogRef.current
    if (!dialog) return

    // Add closing class → triggers CSS animation
    dialog.classList.add('closing')

    // Wait for animation to finish BEFORE closing
    setTimeout(() => {
      dialog.classList.remove('closing')
      dialog.close()
    }, 300) // must match CSS duration (0.35s ≈ 300ms)
}

  return (
    <>
      {/* cardRef is attached here — PhotoGallery uses it to call scrollIntoView */}
      <div
        className="photo-card"
        ref={cardRef}
        data-photo-id={photo.id}
        onClick={openModal}
      >
        <div className="photo-image-container">
          {!imageError && isImageFile() ? (
            <img
              src={getImageUrl()}
              alt={getFileName()}
              onError={() => setImageError(true)}
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
                      >✕</button>
                    </span>
                  )
                })}
              </div>
            )}
          </div>
          {photo.scenario && (
            <p className="photo-description">{photo.scenario}</p>
          )}
          <p className="photo-date">{new Date(photo.created_at).toLocaleDateString()}</p>
        </div>
      </div>

      {/* Modal Dialog */}
      <dialog ref={dialogRef} className="photo-modal">
        <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={closeModal}>✕</button>
            <div className="modal-image-container">
              {!imageError && isImageFile() ? (
                <img
                  src={getImageUrl()}
                  alt={getFileName()}
                  onError={() => setImageError(true)}
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
                  <span className="label">People:</span>
                  {photo.person_ids && photo.person_ids.length > 0 ? (
                    <div className="modal-person-tags">
                      {photo.person_ids.map((personId, idx) => {
                        const name = photo.person_names?.[idx] || `Person ${personId}`
                        const color = photo.person_colors?.[idx] || '#e8f5e9'
                        return (
                          <span
                            key={`modal-${photo.id}-${personId}-${idx}`}
                            className="modal-person-badge"
                            style={{
                              backgroundColor: color,
                              color: getContrastColor(color),
                              borderColor: color,
                            }}
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
                    <span className="value">No faces detected</span>
                  )}
                </div>
                <div className="detail-item">
                  <span className="label">Add Label</span>
                  <div className="add-label-row">
                    <select
                      value={selectedPersonForAdd}
                      onChange={e => setSelectedPersonForAdd(e.target.value)}
                    >
                      <option value="">{loadingPersons ? 'Loading...' : 'Select a person'}</option>
                      {personsList.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                      <option value="other">Other...</option>
                    </select>
                    {selectedPersonForAdd === 'other' && (
                      <input
                        type="text"
                        value={customPersonLabel}
                        onChange={e => setCustomPersonLabel(e.target.value)}
                        placeholder="Type name..."
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
                      Add Label
                    </button>
                  </div>
                </div>
                <div className="detail-item">
                  <span className="label">Added:</span>
                  <span className="value">{new Date(photo.created_at).toLocaleString()}</span>
                </div>
              </div>
            </div>
          </div>
      </dialog>
    </>
  )
}

export default PhotoCard