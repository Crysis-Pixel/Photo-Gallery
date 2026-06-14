import { useState, useRef, useEffect } from 'react'
import './App.css'
import PhotoGallery from './components/PhotoGallery'
import PersonManager from './components/PersonManager'
import Sidebar from './components/Sidebar'
import { BASE_URL } from './api'

// Poll the backend health endpoint until it responds, then resolve.
// Retries every `intervalMs` up to `timeoutMs` total.
async function waitForBackend(timeoutMs = 60000, intervalMs = 800) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE_URL}/`, { signal: AbortSignal.timeout(600) })
      if (res.ok) return true
    } catch {
      // Backend not ready yet — keep waiting
    }
    await new Promise(r => setTimeout(r, intervalMs))
  }
  return false // timed out
}

function App() {
  const [persons, setPersons] = useState([])
  const [refreshKey, setRefreshKey] = useState(0)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const photoGalleryRef = useRef(null)

  // --- Backend startup state ---
  const [backendReady, setBackendReady] = useState(false)
  const [backendFailed, setBackendFailed] = useState(false)
  const [startupDots, setStartupDots] = useState('.')

  useEffect(() => {
    // Animate the loading dots while waiting
    const dotInterval = setInterval(() => {
      setStartupDots(d => d.length >= 3 ? '.' : d + '.')
    }, 500)

    waitForBackend().then(ok => {
      clearInterval(dotInterval)
      if (ok) {
        setBackendReady(true)
      } else {
        setBackendFailed(true)
      }
    })

    return () => clearInterval(dotInterval)
  }, [])

  const scrollToPhoto = (photoId) => {
    photoGalleryRef.current?.scrollToPhoto(photoId)
  }

  const refreshAll = () => {
    setRefreshKey(prev => prev + 1)
  }

  // --- Loading / error screens ---
  if (backendFailed) {
    return (
      <div className="startup-screen">
        <div className="startup-card startup-card--error">
          <div className="startup-icon">⚠️</div>
          <h2>Could not connect to backend</h2>
          <p>The background service failed to start within 60 seconds.<br />Try restarting the app.</p>
          <button className="startup-retry-btn" onClick={() => window.location.reload()}>Retry</button>
        </div>
      </div>
    )
  }

  if (!backendReady) {
    return (
      <div className="startup-screen">
        <div className="startup-card">
          <div className="startup-spinner" />
          <h2>Starting Photo Gallery{startupDots}</h2>
          <p>Loading AI models and services.<br />This may take a moment on first launch.</p>
        </div>
      </div>
    )
  }

  // --- Main app ---
  return (
    <>
      <div className="app">
        <header className="app-header">
          <button
            className="sidebar-toggle-btn"
            onClick={() => setIsSidebarOpen(true)}
            aria-label="Open settings"
          >
            ☰
          </button>
          <h1>Photo Gallery</h1>
        </header>

        <main>
          <PersonManager
            onPersonsChange={setPersons}
            onPhotoClick={scrollToPhoto}
            refreshKey={refreshKey}
          />
          <PhotoGallery
            persons={persons}
            ref={photoGalleryRef}
            refreshKey={refreshKey}
            onRefresh={refreshAll}
          />
        </main>
      </div>

      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onRefresh={refreshAll}
      />
    </>
  )
}

export default App