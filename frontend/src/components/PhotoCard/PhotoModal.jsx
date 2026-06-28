import { useState, useEffect, useRef, useMemo } from 'react'
import { FILES_API as API } from '../../api'

export default function PhotoModal({ photo: initialPhoto, isOpen, onClose, onPhotoUpdated, onRefresh, fetchPersons, getSortedPersons, getContrastColor, formatDateTime, isVideoFile, isImageFile, getImageUrl, getFileName, handleClearPersonTag }) {
  const [photo, setPhoto] = useState(initialPhoto)
  const [selectedFace, setSelectedFace] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [selectedMergeTarget, setSelectedMergeTarget] = useState('')
  const [selectedPersonForAdd, setSelectedPersonForAdd] = useState('')
  const [customPersonLabel, setCustomPersonLabel] = useState('')
  const [isRescanning, setIsRescanning] = useState(false)
  const [isRotating, setIsRotating] = useState(false)
  const [imgAspectRatio, setImgAspectRatio] = useState('auto')
  const [needsRefresh, setNeedsRefresh] = useState(false)
  const [faceOverlayVersion, setFaceOverlayVersion] = useState(0)
  const [isLivePlaying, setIsLivePlaying] = useState(false)
  
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

  // Deduplicate person tags — after a rescan the server response is authoritative,
  // but stale denormalized arrays can briefly contain duplicates. Always derive a
  // clean unique list from the faces array when it's present; fall back to the
  // top-level arrays only when faces are absent (e.g. non-face photos).
  const personTags = useMemo(() => {
    if (photo.faces && photo.faces.length > 0) {
      const seen = new Set()
      return photo.faces
        .filter(f => f.person_id != null)
        .filter(f => {
          if (seen.has(f.person_id)) return false
          seen.add(f.person_id)
          return true
        })
        .map(f => ({
          personId: f.person_id,
          name: f.person_name || `Person ${f.person_id}`,
          color: f.person_color || null,
        }))
    }
    // Fallback: zip top-level arrays, deduplicate by personId
    const seen = new Set()
    return (photo.person_ids || [])
      .map((id, i) => ({
        personId: id,
        name: photo.person_names?.[i] || `Person ${id}`,
        color: photo.person_colors?.[i] || null,
      }))
      .filter(t => {
        if (seen.has(t.personId)) return false
        seen.add(t.personId)
        return true
      })
  }, [photo])

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
        updated._cacheBuster = Date.now()
        setPhoto(updated)
        // Push to grid immediately so the card reflects new tags without a page refresh
        onPhotoUpdated?.(updated)
        setSelectedFace(null)
        setFaceOverlayVersion(v => v + 1)
        fetchPersons?.()
        // Also trigger a background gallery refresh so person filter counts etc. stay in sync.
        // We set needsRefresh=false so the close handler won't double-fire it.
        onRefresh?.()
        setNeedsRefresh(false)
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
      if (updated) {
        updated._cacheBuster = Date.now()
        setPhoto(updated)
        onPhotoUpdated?.(updated)
      }
    } catch (err) { console.error(err) }
  }

  const handleRotate = async (degrees) => {
    if (!isImageFile()) return
    setIsRotating(true)
    try {
      const response = await fetch(`${API}/${photo.id}/rotate?degrees=${degrees}`, { method: 'POST' })
      if (response.ok) {
        const updated = await response.json()
        updated._cacheBuster = Date.now()
        setPhoto(updated)
        onPhotoUpdated?.(updated)
        setSelectedFace(null)
        setFaceOverlayVersion(v => v + 1)
        await refreshPhoto()
      }
    } catch (err) { console.error(err) }
    finally { setIsRotating(false) }
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
        <div 
          className="modal-image-wrapper" 
          style={{ aspectRatio: imgAspectRatio, position: 'relative' }}
          onPointerDown={() => photo.live_video_id && setIsLivePlaying(true)}
          onPointerUp={() => setIsLivePlaying(false)}
          onPointerLeave={() => setIsLivePlaying(false)}
          onPointerCancel={() => setIsLivePlaying(false)}
        >
          {/* Live Photo Badge */}
          {photo.live_video_id && (
            <div className="live-photo-badge" style={{
              position: 'absolute',
              top: '16px',
              left: '16px',
              background: 'rgba(0,0,0,0.5)',
              backdropFilter: 'blur(4px)',
              color: 'white',
              borderRadius: '16px',
              padding: '6px 10px',
              fontSize: '0.85rem',
              fontWeight: '600',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              zIndex: 10,
              pointerEvents: 'none',
              opacity: isLivePlaying ? 0 : 1,
              transition: 'opacity 0.2s'
            }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3"></circle>
                <circle cx="12" cy="12" r="8"></circle>
              </svg>
              LIVE
            </div>
          )}

          {/* Actual Video for Live Photo */}
          {photo.live_video_id && isLivePlaying && (
            <video 
              src={`${API}/${photo.live_video_id}/content`} 
              className="modal-image" 
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', zIndex: 5 }}
              autoPlay 
              playsInline 
              muted
              loop
            />
          )}

          <img
            src={getImageUrl()}
            alt={getFileName()}
            onLoad={(e) => {
              const { naturalWidth, naturalHeight } = e.target;
              if (naturalWidth && naturalHeight) setImgAspectRatio(`${naturalWidth} / ${naturalHeight}`);
            }}
            className="modal-image"
            style={{ opacity: isLivePlaying ? 0 : 1 }}
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
                {personTags.map(({ personId, name, color }) => (
                  <span key={personId} className="modal-person-badge" style={{ backgroundColor: color, color: getContrastColor(color) }}>
                    {name}
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
                  <button onClick={addLabelFromDropdown} disabled={!selectedPersonForAdd} className="add-label-btn">{selectedFace ? 'Update Tag' : 'Add'}</button>
                </div>
              </div>
            </div>
          </div>

          <div className="modal-footer">
            <span className="modal-date">Added {formatDateTime(photo.created_at)}</span>
            <div className="modal-rotate-btns">
              <button onClick={() => handleRotate(90)} disabled={!isImageFile() || isRotating} className="rotate-btn" title="Rotate left 90°">↺</button>
              <button onClick={() => handleRotate(270)} disabled={!isImageFile() || isRotating} className="rotate-btn" title="Rotate right 90°">↻</button>
            </div>
            <button onClick={handleRescan} disabled={isRescanning} className="add-label-btn" style={{ width: 'auto' }}>{isRescanning ? 'Scanning...' : 'Rescan'}</button>
          </div>
        </div>
      </div>
    </dialog>
  )
}