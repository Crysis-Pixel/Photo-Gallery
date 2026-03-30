import { useState, useEffect, useRef, forwardRef, useImperativeHandle, createRef } from 'react'
import PhotoCard from './PhotoCard'
import '../styles/PhotoGallery.css'

const PhotoGallery = forwardRef(function PhotoGallery({ persons: personsProp }, ref) {
  const [photos, setPhotos] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [folderPath, setFolderPath] = useState('')
  const [folders, setFolders] = useState([])
  const [showFolders, setShowFolders] = useState(false)
  const [folderError, setFolderError] = useState(null)
  const [folderSaving, setFolderSaving] = useState(false)
  const [scanLoading, setScanLoading] = useState(false)
  const [filterCategory, setFilterCategory] = useState('')
  const [filterScenario, setFilterScenario] = useState('')
  const [filterPerson, setFilterPerson] = useState('')

  const persons = personsProp || []
  const firstFolder = folders.length > 0 ? folders[0].path : ''

  // ─── Refs for scrolling ───────────────────────────────────────────────────
  // Each photo gets its own ref. When photos change (e.g. after a filter),
  // we create new refs only for photos that don't already have one.
  const cardRefs = useRef({})

  useEffect(() => {
    photos.forEach(photo => {
      if (!cardRefs.current[photo.id]) {
        cardRefs.current[photo.id] = createRef()
      }
    })
  }, [photos])

  // ─── Expose scrollToPhoto to parent (App) ────────────────────────────────
 useImperativeHandle(ref, () => ({
  scrollToPhoto: (photoId) => {
    setFilterCategory('')
    setFilterScenario('')
    setFilterPerson('')

    setTimeout(() => {
      const cardRef = cardRefs.current[photoId]

      if (cardRef?.current) {
        cardRef.current.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
        })

        // highlight
        cardRef.current.classList.add('photo-card--highlight')
        setTimeout(() => {
          cardRef.current?.classList.remove('photo-card--highlight')
        }, 1800)

        // open modal
        setTimeout(() => {
          cardRef.current?.click()
        }, 400)
      }
    }, 100) // wait for DOM update
  },
}))

  // ─── Data fetching (unchanged) ───────────────────────────────────────────
  useEffect(() => {
    fetchFolders()
    fetchPhotos()
  }, [])

  const fetchPhotos = async () => {
    try {
      setLoading(true)
      const response = await fetch('http://localhost:8000/files/')
      if (!response.ok) throw new Error('Failed to fetch photos')
      const data = await response.json()
      setPhotos(data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const fetchFolders = async () => {
    try {
      const response = await fetch('http://localhost:8000/files/folder')
      if (!response.ok) { setFolders([]); return }
      const data = await response.json()
      setFolders(Array.isArray(data) ? data : [])
      setFolderError(null)
    } catch {
      setFolders([])
    }
  }

  const saveFolderPath = async (path = null) => {
    const folderToSave = (path || folderPath).trim()
    if (!folderToSave) { setFolderError('Please add a folder path first.'); return }
    try {
      setFolderSaving(true)
      const response = await fetch('http://localhost:8000/files/folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: folderToSave }),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => null)
        throw new Error(err?.detail || 'Failed to save folder path')
      }
      await response.json()
      setFolderPath('')
      setFolderError(null)
      await fetchFolders()
      await fetchPhotos()
    } catch (err) {
      setFolderError(err.message)
    } finally {
      setFolderSaving(false)
    }
  }

  const rescanFolder = async () => {
    if (!folders.length) { setFolderError('Please add a folder before rescanning.'); return }
    try {
      setScanLoading(true)
      setError(null)
      const response = await fetch('http://localhost:8000/files/rescan', { method: 'POST' })
      if (!response.ok) {
        const err = await response.json().catch(() => null)
        throw new Error(err?.detail || `HTTP error! status: ${response.status}`)
      }
      await fetchPhotos()
    } catch (err) {
      setError(err.message)
    } finally {
      setScanLoading(false)
    }
  }

  const handleRemoveFolder = async (folderId) => {
    try {
      const response = await fetch(`http://localhost:8000/files/folder/${folderId}`, { method: 'DELETE' })
      if (!response.ok) {
        const err = await response.json().catch(() => null)
        throw new Error(err?.detail || 'Failed to remove folder')
      }
      await fetchFolders()
      await fetchPhotos()
    } catch (err) {
      setFolderError(err.message)
    }
  }

  const getUniqueCategories = () =>
    Array.from(new Set(photos.map(p => p.category).filter(Boolean))).sort()

  const getUniqueScenarios = () =>
    Array.from(new Set(photos.map(p => p.scenario).filter(Boolean)))

  const filteredPhotos = photos.filter(photo => {
    const categoryMatch = !filterCategory || photo.category === filterCategory
    const scenarioMatch = !filterScenario || photo.scenario === filterScenario
    const personMatch = !filterPerson ||
      (Array.isArray(photo.person_ids) && photo.person_ids.includes(Number(filterPerson)))
    return categoryMatch && scenarioMatch && personMatch
  })

  if (error) {
    return (
      <div className="gallery-container">
        <div className="error-message">
          <p>Error: {error}</p>
          <p>Make sure the backend server is running on http://localhost:8000</p>
          <button onClick={() => { setError(null); fetchPhotos() }}>Retry</button>
        </div>
      </div>
    )
  }

  return (
    <div className="gallery-container">
      {/* Folder controls (unchanged) */}
      <div className="folder-controls">
        <div className="folder-status">
          <strong>Current folders:</strong>
          <span className="folder-current-path">{firstFolder || 'Not configured'}</span>
          {firstFolder && folders.length > 0 && (
            <button 
              type="button" 
              className="remove-folder-btn"
              onClick={() => handleRemoveFolder(folders[0].id)}
              title="Remove first folder"
            >
              ✕
            </button>
          )}
          <button type="button" className="folder-expand-toggle"
            onClick={() => setShowFolders(p => !p)} aria-expanded={showFolders}>
            {showFolders ? '▾' : '▸'}
          </button>
        </div>

        {showFolders && (
          <div className="folder-list">
            {folders.length === 0 ? (
              <div className="folder-empty">No folders configured yet.</div>
            ) : folders.length === 1 ? (
              <div className="folder-empty">No additional folders.</div>
            ) : (
              <ul>
                {folders.slice(1).map(folder => (
                  <li key={folder.id}>
                    <span>{folder.path}</span>
                    <button type="button" className="remove-folder-btn"
                      onClick={() => handleRemoveFolder(folder.id)}>✕</button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="folder-actions">
          <div className="folder-input-row">
            <input type="text" value={folderPath} onChange={e => setFolderPath(e.target.value)}
              placeholder="Enter folder path anywhere on your PC" />
            <button type="button" className="folder-picker-button"
              onClick={() => saveFolderPath()} disabled={folderSaving}>
              {folderSaving ? 'Adding...' : 'Add folder'}
            </button>
          </div>
          <button className="rescan-button" onClick={rescanFolder}
            disabled={scanLoading || folders.length === 0}
            title={folders.length === 0 ? 'Add folder(s) first' : 'Rescan all configured folders'}>
            {scanLoading ? 'Rescanning...' : 'Rescan folders'}
          </button>
        </div>
        {folderError && <div className="error-message">{folderError}</div>}
        <div className="folder-note">
          Add one or more folder paths so the app can scan images from anywhere on your PC.
        </div>
      </div>

      {/* Filters (unchanged) */}
      <div className="filters">
        <div className="filter-group">
          <label>Category:</label>
          <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)}>
            <option value="">All Categories</option>
            {getUniqueCategories().map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>Person:</label>
          <select value={filterPerson} onChange={e => setFilterPerson(e.target.value)}>
            <option value="">All Persons</option>
            {persons.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>Scenario:</label>
          <select value={filterScenario} onChange={e => setFilterScenario(e.target.value)}>
            <option value="">All Scenarios</option>
            {getUniqueScenarios().map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <button className="refresh-btn" onClick={fetchPhotos}>Refresh</button>
      </div>

      {loading ? (
        <div className="loading">Loading photos...</div>
      ) : (
        <>
          <div className="photo-count">
            Showing {filteredPhotos.length} of {photos.length} photos
          </div>
          <div className="gallery-grid">
            {filteredPhotos.length > 0
              ? filteredPhotos.map(photo => (
                  <PhotoCard
                    key={photo.id}
                    photo={photo}
                    cardRef={cardRefs.current[photo.id]}   // ← attach the ref
                    onPersonTagCleared={fetchPhotos}
                  />
                ))
              : <div className="no-photos">No photos found</div>
            }
          </div>
        </>
      )}
    </div>
  )
})

export default PhotoGallery