import { useState, useEffect } from 'react'
import '../styles/Sidebar.css'

const Sidebar = ({ isOpen, onClose, onRefresh }) => {
  const [folderPath, setFolderPath] = useState('')
  const [folders, setFolders] = useState([])
  const [folderError, setFolderError] = useState(null)
  const [folderSaving, setFolderSaving] = useState(false)
  const [scanLoading, setScanLoading] = useState(false)
  const [checkLoading, setCheckLoading] = useState(false)

  useEffect(() => {
    if (isOpen) {
      fetchFolders()
    }
  }, [isOpen])

  const fetchFolders = async () => {
    try {
      const res = await fetch('http://localhost:8000/files/folder')
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
        const res = await fetch('http://localhost:8000/files/folder', {
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
        
        // Show success message
        alert('Folder added successfully! Scanning will start in the background.')
        
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
      await fetch('http://localhost:8000/files/rescan', { method: 'POST' })
      fetchFolders()
      onRefresh?.()                    // ← Refresh main UI
    } catch (e) {
      console.error('Rescan failed:', e)
      setFolderError('Rescan failed')
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
      const response = await fetch('http://localhost:8000/files/recheck', { method: 'POST' })

      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err?.detail || `Recheck failed: ${response.status}`)
      }

      const result = await response.json()
      console.log('Recheck completed:', result)

      alert(`Recheck finished!\nNew files: ${result.new_files || 0}\nRetagged: ${result.retagged_files || 0}`)

      onRefresh?.()                    // ← Refresh main UI

    } catch (e) {
      console.error('Recheck error:', e)
      setFolderError(e.message || 'Recheck failed. Check console for details.')
    } finally {
      setCheckLoading(false)
    }
  }

const removeFolder = async (id) => {

  try {
    const res = await fetch(`http://localhost:8000/files/folder/${id}`, { method: 'DELETE' });
    
    if (res.ok) {
      fetchFolders();           // refresh sidebar
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
              <input
                type="text"
                value={folderPath}
                onChange={(e) => setFolderPath(e.target.value)}
                placeholder="Enter folder path on your PC"
              />
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
          </div>

          {folderError && <div className="sidebar-error">{folderError}</div>}
        </div>
      </div>

      {isOpen && <div className="sidebar-overlay" onClick={onClose} />}
    </>
  )
}

export default Sidebar