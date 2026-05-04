import { useState, useEffect, useRef, useMemo } from 'react'

const API = `http://${window.location.hostname}:8000/files`

export default function PhotoModal({ photo: initialPhoto, isOpen, onClose, onPhotoUpdated, onRefresh, fetchPersons, getSortedPersons, getContrastColor, formatDateTime, isVideoFile, isImageFile, getImageUrl, getFileName, handleClearPersonTag }) {
  const [photo, setPhoto] = useState(initialPhoto)
  const [selectedFace, setSelectedFace] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [selectedMergeTarget, setSelectedMergeTarget] = useState('')
  const [selectedPersonForAdd, setSelectedPersonForAdd] = useState('')
  const [customPersonLabel, setCustomPersonLabel] = useState('')
  const [isRescanning, setIsRescanning] = useState(false)
  const [imgAspectRatio, setImgAspectRatio] = useState('auto')
  const [needsRefresh, setNeedsRefresh] = useState(false)
  const [faceOverlayVersion, setFaceOverlayVersion] = useState(0)
  
  const dialogRef = useRef(null)
  const modalVideoRef = useRef(null)

  // Sync with prop if it changes from outside
  useEffect(() => {
    setPhoto(initialPhoto)
  }, [initialPhoto])

  useEffect(() => {
    if (isOpen) {
      if (dialogRef.current) dialogRef.current.showModal()
      fetchPersons?.()
    }
  }, [isOpen])

  useEffect(() => {
    if (selectedFace) {
      const faceInPhoto = photo.faces?.find(f => f.id === selectedFace.id)
      const currentName = faceInPhoto?.person_name || selectedFace.person_name || `Person ${selectedFace.person_id}`
      setRenameValue(currentName)
    }
  }, [selectedFace, photo])

  const handleClose = () => {
    if (modalVideoRef.current) {
      modalVideoRef.current.pause()
      modalVideoRef.current.currentTime = 0
    }
    setSelectedFace(null)
    if (dialogRef.current) {
        dialogRef.current.classList.add('closing')
        setTimeout(() => {
          if (dialogRef.current) {
            dialogRef.current.classList.remove('closing')
            dialogRef.current.close()
          }
          onClose()
          if (needsRefresh) {
            onRefresh?.()
            setNeedsRefresh(false)
          }
        }, 280)
    } else {
        onClose()
    }
  }

  const refreshPhoto = async () => {
    try {
      const res = await fetch(`${API}/${photo.id}`)
      if (res.ok) {
        const updated = await res.json()
        updated._cacheBuster = Date.now()
        setPhoto(updated)
        onPhotoUpdated?.(updated)
        return updated
      }
    } catch (err) { console.error(err) }
  }

  const handleRenamePerson = async (personId) => {
    const newName = renameValue.trim()
    if (!newName) return
    try {
      const response = await fetch(`${API}/persons/${personId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName })
      })
      if (response.ok) {
        setNeedsRefresh(true)
        await refreshPhoto()
        fetchPersons?.()
        setSelectedFace(null)
      }
    } catch (err) { console.error(err) }
  }

  const handleMergePerson = async (personId) => {
    if (!selectedMergeTarget || !confirm('Merge this person?')) return
    try {
      const response = await fetch(`${API}/persons/${personId}/merge/${selectedMergeTarget}`, { method: 'POST' })
      if (response.ok) {
        setNeedsRefresh(true)
        await refreshPhoto()
        fetchPersons?.()
        setSelectedMergeTarget('')
        setSelectedFace(null)
      }
    } catch (err) { console.error(err) }
  }

  const addLabelFromDropdown = async (event) => {
    event.stopPropagation()
    if (!selectedPersonForAdd) return
    try {
      const body = selectedPersonForAdd === 'other'
        ? { person_name: customPersonLabel.trim() }
        : { person_id: Number(selectedPersonForAdd) }
      
      const response = await fetch(selectedFace ? `${API}/faces/${selectedFace.id}` : `${API}/${photo.id}/persons`, {
        method: selectedFace ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (response.ok) {
        const updated = await response.json()
        updated._cacheBuster = Date.now()
        setPhoto(updated)
        onPhotoUpdated?.(updated)
        setSelectedPersonForAdd('')
        setCustomPersonLabel('')
        setSelectedFace(null)
        fetchPersons?.()
      }
    } catch (err) { console.error(err) }
  }

  const handleRescan = async (event) => {
    event.stopPropagation()
    setIsRescanning(true)
    try {
      await fetch(`${API}/${photo.id}/thumbnail`, { method: 'DELETE' }).catch(() => {})
      const response = await fetch(`${API}/${photo.id}/rescan`, { method: 'POST' })
      if (response.ok) {
        const updated = await response.json()
        // Add cache buster to force image reload in the UI
        updated._cacheBuster = Date.now()
        setPhoto(updated)
        onPhotoUpdated?.(updated)
        setSelectedFace(null) // Clear selected face after rescan
        setFaceOverlayVersion(v => v + 1) // Force face overlay remount
        fetchPersons?.()
      }
    } catch (err) { console.error(err) }
    finally { setIsRescanning(false) }
  }

  const handleCategoryChange = async (newCategory) => {
    try {
      const response = await fetch(`${API}/${photo.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: newCategory || null })
      })
      if (response.ok) {
        const updated = await response.json()
        updated._cacheBuster = Date.now()
        setPhoto(updated)
        onPhotoUpdated?.(updated)
      }
    } catch (err) { console.error(err) }
  }

  const handleLocalRemoveTag = async (personId, e) => {
    try {
      const updated = await handleClearPersonTag(personId, e)
      if (updated) setPhoto(updated)
    } catch (err) { console.error(err) }
  }

  const renderMedia = () => {
    if (isVideoFile()) {
      return (
        <div className="modal-video-wrapper">
          <video ref={modalVideoRef} src={getImageUrl()} className="modal-image" controls preload="metadata" controlsList="nodownload" playsInline />
        </div>
      )
    }
    if (isImageFile()) {
      return (
        <div className="modal-image-wrapper" style={{ aspectRatio: imgAspectRatio }}>
          <img
            src={getImageUrl()}
            alt={getFileName()}
            onLoad={(e) => {
              const { naturalWidth, naturalHeight } = e.target;
              if (naturalWidth && naturalHeight) setImgAspectRatio(`${naturalWidth} / ${naturalHeight}`);
            }}
            className="modal-image"
          />
           {photo.faces?.map(face => (
            face.box_left != null && (
              <div
                key={`${face.id}-${faceOverlayVersion}`}
                className={`face-box ${selectedFace?.id === face.id ? 'active' : ''}`}
                style={{
                  left: `${face.box_left * 100}%`,
                  top: `${face.box_top * 100}%`,
                  width: `${face.box_width * 100}%`,
                  height: `${face.box_height * 100}%`,
                  borderColor: face.person_color || '#e8f5e9'
                }}
                onClick={(e) => { e.stopPropagation(); setSelectedFace(selectedFace?.id === face.id ? null : face); }}
              >
                <span className="face-box-label" style={{ backgroundColor: face.person_color || '#e8f5e9', color: getContrastColor(face.person_color || '#e8f5e9') }}>
                  {face.person_name || `Person ${face.person_id}`}
                </span>
              </div>
            )
          ))}
        </div>
      )
    }
    return <div className="no-image-placeholder-large">🖼️ Could not load</div>
  }

  return (
    <dialog ref={dialogRef} className="photo-modal" onClick={(e) => e.target === dialogRef.current && handleClose()} onCancel={(e) => { e.preventDefault(); handleClose(); }}>
      <div className="modal-inner" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={handleClose}>✕</button>
        <div className="modal-image-container">{renderMedia()}</div>
        <div className="modal-info">
          <div className="modal-info-scroll">
            <div className="modal-header">
              <h2 className="modal-title">{getFileName()}</h2>
              <p className="modal-subtitle">{photo.path}</p>
            </div>
            <div className="modal-divider" />
            
            <div className="detail-item">
              <span className="label">Category</span>
              <select className="value" value={photo.category || ''} onChange={(e) => handleCategoryChange(e.target.value)}>
                <option value="">—</option>
                {["selfie", "group photo", "family photo", "birthday", "wedding", "party", "graduation", "holiday", "travel", "nature", "cityscape", "beach", "indoor", "food", "pet", "car", "screenshot", "document", "anime", "artwork", "meme", "video"].sort().map(cat => <option key={cat} value={cat}>{cat}</option>)}
              </select>
            </div>

            <div className="detail-item">
              <span className="label">Description</span>
              <span className="value">{photo.scenario || '—'}</span>
            </div>

            <div className="detail-item">
              <span className="label">People</span>
              <div className="modal-person-tags">
                {photo.person_ids?.map((personId, idx) => (
                  <span key={personId} className="modal-person-badge" style={{ backgroundColor: photo.person_colors?.[idx], color: getContrastColor(photo.person_colors?.[idx]) }}>
                    {photo.person_names?.[idx] || `Person ${personId}`}
                    <button className="modal-person-badge-remove" onClick={(e) => handleLocalRemoveTag(personId, e)}>✕</button>
                  </span>
                ))}
              </div>
            </div>

            <div className="modal-divider" />

            <div className="detail-item">
              <span className="label">{selectedFace ? `Relabel Target Face` : 'Tag a person'}</span>
              <div className="add-label-section">
                {selectedFace && (
                  <div className="relabel-section">
                    <div className="add-label-row">
                      <input type="text" value={renameValue} onChange={e => setRenameValue(e.target.value)} placeholder="New name..." />
                      <button onClick={() => handleRenamePerson(selectedFace.person_id)} className="add-label-btn">Save</button>
                    </div>
                    <div className="add-label-row">
                      <select value={selectedMergeTarget} onChange={e => setSelectedMergeTarget(e.target.value)}>
                        <option value="">Merge with...</option>
                        {getSortedPersons().filter(p => p.id !== selectedFace.person_id).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                      <button onClick={() => handleMergePerson(selectedFace.person_id)} disabled={!selectedMergeTarget} className="add-label-btn">Merge</button>
                    </div>
                    <div className="modal-divider" />
                  </div>
                )}
                <div className="add-label-row">
                  <select value={selectedPersonForAdd} onChange={e => setSelectedPersonForAdd(e.target.value)}>
                    <option value="">Select person...</option>
                    {getSortedPersons().map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    <option value="other">Other...</option>
                  </select>
                  {selectedPersonForAdd === 'other' && <input type="text" value={customPersonLabel} onChange={e => setCustomPersonLabel(e.target.value)} placeholder="Name..." />}
                  <button onClick={addLabelFromDropdown} disabled={!selectedPersonForAdd} className="add-label-btn">Add</button>
                </div>
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <span className="modal-date">Added {formatDateTime(photo.created_at)}</span>
            <button onClick={handleRescan} disabled={isRescanning} className="add-label-btn" style={{ width: 'auto' }}>{isRescanning ? 'Scanning...' : 'Rescan'}</button>
          </div>
        </div>
      </div>
    </dialog>
  )
}
