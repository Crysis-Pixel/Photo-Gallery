import { useState, useEffect } from 'react'
import '../styles/Sidebar.css'
import { BASE_URL } from '../api'
import { open } from '@tauri-apps/plugin-dialog'

const MODEL_LABELS = {
  insightface: 'Face Detection (InsightFace)',
  clip: 'Image Labels (CLIP)',
  blip: 'Description (BLIP)',
  facenet: 'Face Detection (FaceNet)',
}

const Sidebar = ({ isOpen, onClose, onRefresh, onScanStart, isScanning }) => {
  const isTauri = window.__TAURI_INTERNALS__ !== undefined;
  
  const handleOpenDialog = async () => {
    if (isTauri) {
      try {
        const selected = await open({
          directory: true,
          multiple: false,
        });
        if (selected) {
          setFolderPath(selected);
        }
      } catch (err) {
        console.error('Failed to open dialog', err);
      }
    }
  };

  const [folderPath, setFolderPath] = useState('')
  const [folders, setFolders] = useState([])
  const [folderError, setFolderError] = useState(null)
  const [folderSaving, setFolderSaving] = useState(false)
  const [scanLoading, setScanLoading] = useState(false)
  const [checkLoading, setCheckLoading] = useState(false)
  const [mergeLoading, setMergeLoading] = useState(false)
  const [mergeResult, setMergeResult] = useState(null)
  const [modelStatus, setModelStatus] = useState(null)
  const [recheckModal, setRecheckModal] = useState({ isOpen: false, title: '', message: '', type: 'info' })
  
  const [albums, setAlbums] = useState([])
  const [persons, setPersons] = useState([])
  const [selectedAlbum, setSelectedAlbum] = useState('')
  const [selectedPerson, setSelectedPerson] = useState('')

  const sortedPersons = [...persons].sort((a, b) => {
    const aIsNamed = !!a.name;
    const bIsNamed = !!b.name;
    
    // Named persons come first
    if (aIsNamed && !bIsNamed) return -1;
    if (!aIsNamed && bIsNamed) return 1;
    
    if (aIsNamed && bIsNamed) {
      // Sort named alphabetically
      return a.name.localeCompare(b.name);
    } else {
      // Sort unnamed by ID (Person 1, Person 2, etc.)
      return a.id - b.id;
    }
  });

  useEffect(() => {
    if (isOpen) {
      fetchFolders()
      fetchModelStatus()
      fetchAlbumsAndPersons()
    }
  }, [isOpen])

  const fetchAlbumsAndPersons = async () => {
    try {
      const [metaRes, personsRes] = await Promise.all([
        fetch(`${BASE_URL}/files/metadata`),
        fetch(`${BASE_URL}/files/persons`)
      ])
      if (metaRes.ok) {
        const data = await metaRes.json()
        setAlbums(data.albums || [])
      }
      if (personsRes.ok) {
        const data = await personsRes.json()
        setPersons(data || [])
      }
    } catch (e) {
      console.error('Failed to fetch filter data', e)
    }
  }

  const fetchModelStatus = async () => {
    try {
      const res = await fetch(`${BASE_URL}/models/status`)
      if (res.ok) {
        setModelStatus(await res.json())
      }
    } catch (e) {
      console.error('Failed to fetch model status:', e)
    }
  }

  const fetchFolders = async () => {
    try {
      const res = await fetch(`${BASE_URL}/files/folder`)
      if (res.ok) {
        const data = await res.json()
        setFolders(Array.isArray(data) ? data : [])
      }
    } catch (e) {
      console.error('Failed to fetch folders:', e)
    }
  }

  const saveFolderPath = async () => {
    const path = folderPath.trim()
    if (!path) return

    setFolderSaving(true)
    setFolderError(null)
    
    try {
        const res = await fetch(`${BASE_URL}/files/folder`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        })

        if (!res.ok) {
            const errorData = await res.json().catch(() => ({}))
            throw new Error(errorData.detail || 'Failed to add folder')
        }

        const data = await res.json()
        console.log('Folder added:', data)
        
        setFolderPath('')
        await fetchFolders()  // Wait for folders to refresh
        
        // Refresh the gallery after a short delay
        setTimeout(() => {
            onRefresh?.()
        }, 2000)
        
    } catch (e) {
        console.error('Failed to add folder:', e)
        setFolderError(e.message || 'Failed to add folder')
    } finally {
        setFolderSaving(false)
    }
}

  const rescanFolders = async () => {
    if (folders.length === 0) return
    setScanLoading(true)
    try {
      await fetch(`${BASE_URL}/files/rescan`, { method: 'POST' })
      fetchFolders()
      onRefresh?.()                    // ← Refresh main UI
    } catch (e) {
      console.error('Rescan failed:', e)
      setFolderError('Rescan failed')
    } finally {
      setScanLoading(false)
    }
  }

  const handleRescanAlbum = async () => {
    if (!selectedAlbum) return
    setScanLoading(true)
    if (onScanStart) onScanStart()
    try {
      await fetch(`${BASE_URL}/files/rescan/album?album=${encodeURIComponent(selectedAlbum)}`, { method: 'POST' })
      setRecheckModal({
        isOpen: true,
        title: 'Album Rescan Started',
        message: `Started scanning all photos in album: ${selectedAlbum}.`,
        type: 'success'
      })
    } catch (e) {
      console.error(e)
    } finally {
      setScanLoading(false)
    }
  }

  const handleRescanPerson = async () => {
    if (!selectedPerson) return
    setScanLoading(true)
    if (onScanStart) onScanStart()
    try {
      await fetch(`${BASE_URL}/files/rescan/person?person_id=${selectedPerson}`, { method: 'POST' })
      setRecheckModal({
        isOpen: true,
        title: 'Person Rescan Started',
        message: 'Started background rescan of all photos containing this person.',
        type: 'success'
      })
    } catch (e) {
      console.error(e)
    } finally {
      setScanLoading(false)
    }
  }

  const checkMissingFilesAndDetails = async () => {
    if (folders.length === 0) {
      setFolderError('Please add a folder before rechecking.')
      return
    }

    setCheckLoading(true)
    setFolderError(null)

    try {
      const response = await fetch(`${BASE_URL}/files/recheck`, { method: 'POST' })

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err?.detail || `Recheck failed: ${response.status}`)
      }

      const result = await response.json()
      console.log('Recheck completed:', result)

      setRecheckModal({
        isOpen: true,
        title: 'Smart Recheck Started',
        message: 'The smart recheck has started in the background. The application is scanning your folders for new files, cleaning up deleted folders, and updating missing AI categories/faces. The main photo grid will refresh automatically as updates arrive.',
        type: 'success'
      })

      onRefresh?.()                    // ← Refresh main UI

    } catch (e) {
      console.error('Recheck error:', e)
      setFolderError(e.message || 'Recheck failed. Check console for details.')
    } finally {
      setCheckLoading(false)
    }
  }


const mergePeopleYouKnow = async () => {
    setMergeLoading(true)
    setMergeResult(null)
    setFolderError(null)
    try {
      const res = await fetch(
        `${BASE_URL}/files/persons/auto-merge?threshold=0.62`,
        { method: 'POST' }
      )
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err?.detail || 'Auto-merge failed')
      }
      const data = await res.json()
      setMergeResult(data)
      if (data.merged > 0) onRefresh?.()
    } catch (e) {
      setFolderError(e.message || 'Auto-merge failed')
    } finally {
      setMergeLoading(false)
    }
  }

const removeFolder = async (id) => {
  try {
    const res = await fetch(`${BASE_URL}/files/folder/${id}`, { method: 'DELETE' });
    
    if (res.ok) {
      await fetchFolders();     // refresh sidebar list
      onRefresh?.();            // refresh gallery + person section
    } else {
      const err = await res.json().catch(() => ({}));
      setFolderError(err.detail || 'Failed to remove folder');
    }
  } catch (e) {
    console.error('Failed to remove folder:', e);
    setFolderError('Failed to remove folder');
  }
};

  return (
    <>
      <div className={`sidebar ${isOpen ? 'open' : ''}`}>
        <div className="sidebar-header">
          <h2>Library Settings</h2>
          <button className="sidebar-close-btn" onClick={onClose}>✕</button>
        </div>

        <div className="sidebar-content">
          <div className="folder-section">
            <h3>Manage Folders</h3>
            
            <div className="folder-list">
              {folders.length === 0 ? (
                <p className="no-folders">No folders added yet.</p>
              ) : (
                folders.map(folder => (
                  <div key={folder.id} className="folder-item">
                    <span className="folder-path">{folder.path}</span>
                    <button 
                      className="remove-folder-btn" 
                      onClick={() => removeFolder(folder.id)}
                    >
                      ✕
                    </button>
                  </div>
                ))
              )}
            </div>

            <div className="add-folder-row">
              <div className="path-input-container" style={{ position: 'relative', flex: 1, display: 'flex' }}>
                <input
                  type="text"
                  value={folderPath}
                  onChange={(e) => setFolderPath(e.target.value)}
                  placeholder="Enter folder path on your PC"
                  style={{ width: '100%', paddingRight: isTauri ? '30px' : '10px' }}
                />
                {isTauri && (
                  <button
                    onClick={handleOpenDialog}
                    title="Browse for folder"
                    style={{
                      position: 'absolute',
                      right: '5px',
                      top: '50%',
                      transform: 'translateY(-50%)',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: '16px',
                      color: '#a9a9a9',
                      padding: '0',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center'
                    }}
                  >
                    📁
                  </button>
                )}
              </div>
              <button 
                className="add-folder-btn" 
                onClick={saveFolderPath}
                disabled={folderSaving || !folderPath.trim()}
              >
                {folderSaving ? 'Adding...' : 'Add Folder'}
              </button>
            </div>

            <button 
              className="rescan-btn" 
              onClick={rescanFolders}
              disabled={scanLoading || folders.length === 0}
            >
              {scanLoading ? 'Rescanning...' : 'Rescan All Folders'}
            </button>

            <button 
              className="check-btn" 
              onClick={checkMissingFilesAndDetails}
              disabled={checkLoading || folders.length === 0}
            >
              {checkLoading ? 'Rechecking...' : 'Check Missing Files and Details'}
            </button>

              <div className="manual-rescan-section">
                <h4 className="manual-rescan-title">Manual Rescan</h4>
                
                <div className="manual-rescan-row">
                  <select 
                    className="manual-rescan-select"
                    value={selectedAlbum} 
                    onChange={e => setSelectedAlbum(e.target.value)}
                  >
                    <option value="">Select Album</option>
                    {albums.map(a => <option key={a} value={a}>{a}</option>)}
                  </select>
                  <button 
                    className="manual-rescan-btn"
                    onClick={handleRescanAlbum} 
                    disabled={!selectedAlbum || scanLoading || isScanning}
                  >
                    Rescan
                  </button>
                </div>

                <div className="manual-rescan-row">
                  <select 
                    className="manual-rescan-select"
                    value={selectedPerson} 
                    onChange={e => setSelectedPerson(e.target.value)}
                  >
                    <option value="">Select Person</option>
                    {sortedPersons.map(p => <option key={p.id} value={p.id}>{p.name || `Person ${p.id}`}</option>)}
                  </select>
                  <button 
                    className="manual-rescan-btn"
                    onClick={handleRescanPerson} 
                    disabled={!selectedPerson || scanLoading || isScanning}
                  >
                    Rescan
                  </button>
                </div>
              </div>

            <button
              className="merge-people-btn"
              onClick={mergePeopleYouKnow}
              disabled={mergeLoading}
            >
              {mergeLoading ? 'Comparing faces…' : '✦ Merge People You Know'}
            </button>

            {mergeResult && (
              <div className="merge-result">
                <span className="merge-result-icon">✓</span>
                <span>
                  <strong>{mergeResult.merged}</strong> merged into known people
                  {mergeResult.skipped > 0 && ` · ${mergeResult.skipped} no match found`}
                </span>
              </div>
            )}
          </div>

          <div className="model-status-section">
            <h3>AI Models</h3>
            <div className="model-list">
              {modelStatus ? (
                Object.entries(MODEL_LABELS).map(([key, label]) => (
                  <div key={key} className="model-item">
                    <span className={`model-dot ${modelStatus[key] ? 'active' : 'inactive'}`} />
                    <span className="model-name">{label}</span>
                    <span className={`model-badge ${modelStatus[key] ? 'active' : 'inactive'}`}>
                      {modelStatus[key] ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                ))
              ) : (
                <p className="no-folders">Loading model status...</p>
              )}
            </div>
          </div>

          {folderError && <div className="sidebar-error">{folderError}</div>}
        </div>
      </div>

      {isOpen && <div className="sidebar-overlay" onClick={onClose} />}

      {recheckModal.isOpen && (
        <div className="custom-modal-overlay" onClick={() => setRecheckModal({ ...recheckModal, isOpen: false })}>
          <div className="custom-modal" onClick={(e) => e.stopPropagation()}>
            <div className="custom-modal-header">
              <div className="custom-modal-icon">
                {recheckModal.type === 'success' ? '✓' : recheckModal.type === 'error' ? '⚠️' : '🔄'}
              </div>
              <h3 className="custom-modal-title">{recheckModal.title}</h3>
            </div>
            <div className="custom-modal-body">
              <p>{recheckModal.message}</p>
            </div>
            <div className="custom-modal-footer">
              <button className="custom-modal-close-btn" onClick={() => setRecheckModal({ ...recheckModal, isOpen: false })}>
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default Sidebar