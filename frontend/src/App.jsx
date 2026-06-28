import { useState, useRef, useEffect, useCallback } from 'react'
import './App.css'
import PhotoGallery from './components/PhotoGallery'
import MemoriesSection from './components/MemoriesSection'
import Sidebar from './components/Sidebar'
import { BASE_URL } from './api'

async function waitForBackend(timeoutMs = 60000, intervalMs = 800) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE_URL}/`, { signal: AbortSignal.timeout(600) })
      if (res.ok) return true
    } catch {
    }
    await new Promise(r => setTimeout(r, intervalMs))
  }
  return false
}

async function waitForModels(timeoutMs = 300000, intervalMs = 2000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE_URL}/models/status`)
      if (res.ok) {
        const data = await res.json()
        if (!data.download_in_progress) return true
      }
    } catch {
      return true
    }
    await new Promise(r => setTimeout(r, intervalMs))
  }
  return true
}

function App() {
  const [persons, setPersons] = useState([])
  const [refreshKey, setRefreshKey] = useState(0)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [activeMemory, setActiveMemory] = useState(null)
  const photoGalleryRef = useRef(null)

  const [backendReady, setBackendReady] = useState(false)
  const [backendFailed, setBackendFailed] = useState(false)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [startupDots, setStartupDots] = useState('.')
  const [isScanning, setIsScanning] = useState(false)

  const [scanProgress, setScanProgress] = useState(0)

  // Stable refresh function — incrementing refreshKey causes both
  // PersonManager and PhotoGallery to re-fetch their data.
  const refreshAll = useCallback(() => {
    setRefreshKey(prev => prev + 1)
  }, [])

  // Track whether a scan was ever active so we know when it finishes.
  const prevScanningRef = useRef(false)

  useEffect(() => {
    const dotInterval = setInterval(() => {
      setStartupDots(d => d.length >= 3 ? '.' : d + '.')
    }, 500)

    waitForBackend().then(ok => {
      clearInterval(dotInterval)
      if (ok) {
        setBackendReady(true)
        setModelsLoading(true)
        waitForModels().then(() => setModelsLoading(false))
      } else {
        setBackendFailed(true)
      }
    })

    return () => clearInterval(dotInterval)
  }, [])

  // Poll scan status every 3 s once backend is ready.
  useEffect(() => {
    if (!backendReady) return
    const checkScanStatus = async () => {
      try {
        const res = await fetch(`${BASE_URL}/files/scan-status`)
        if (res.ok) {
          const data = await res.json()
          setIsScanning(data.scan_active)
          setScanProgress(data.percentage || 0)
        }
      } catch (err) {
        console.error('Failed to fetch scan status:', err)
      }
    }
    checkScanStatus()
    const intervalId = setInterval(checkScanStatus, 3000)
    return () => clearInterval(intervalId)
  }, [backendReady])

  // While scanning: refresh UI every 4 s so new AI tags appear incrementally.
  // When scanning finishes: fire one final refresh to catch the last batch.
  useEffect(() => {
    if (!backendReady) return

    if (isScanning) {
      prevScanningRef.current = true
      const id = setInterval(() => refreshAll(), 4000)
      return () => clearInterval(id)
    } else {
      // Only fire a completion refresh if a scan was actually running before.
      if (prevScanningRef.current) {
        prevScanningRef.current = false
        refreshAll()
      }
    }
  }, [isScanning, backendReady, refreshAll])

  const scrollToPhoto = (photoId) => {
    photoGalleryRef.current?.scrollToPhoto(photoId)
  }

  const filterByPersonAndScroll = (personId, photoId) => {
    setActiveMemory(null)  // clear memory filter when navigating to a person photo
    photoGalleryRef.current?.filterByPersonAndScroll(personId, photoId)
  }

  const handleMemorySelect = (memory) => {
    setActiveMemory(memory)
  }

  if (backendFailed) {
    return (
      <div className="startup-screen">
        <div className="startup-card startup-card--error">
          <div className="startup-icon">⚠️</div>
          <h2>Could not connect to backend</h2>
          <p>The backend service failed to start within 60 seconds.<br />Try restarting the app. If the issue persists, check the console logs.</p>
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
          <p>Loading services...</p>
        </div>
      </div>
    )
  }

  if (modelsLoading) {
    return (
      <div className="startup-screen">
        <div className="startup-card">
          <div className="startup-spinner" />
          <h2>Downloading AI Models{startupDots}</h2>
          <p>First-time setup — downloading AI models in the background.<br />This may take a few minutes depending on your connection.</p>
        </div>
      </div>
    )
  }

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
          <div className="header-actions">
            {isScanning && (
              <div className="scanning-badge progress-badge">
                <svg viewBox="0 0 36 36" className="circular-chart">
                  <path className="circle-bg"
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                  <path className="circle"
                    strokeDasharray={`${scanProgress}, 100`}
                    d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  />
                  <text x="18" y="20.8" className="percentage">{scanProgress}%</text>
                </svg>
                <span>AI Scanning Images...</span>
              </div>
            )}
          </div>
        </header>

        <main>
          <MemoriesSection
            onPersonsChange={setPersons}
            onPhotoClick={scrollToPhoto}
            onPersonPhotoClick={filterByPersonAndScroll}
            refreshKey={refreshKey}
            onMemorySelect={handleMemorySelect}
          />
          <PhotoGallery
            persons={persons}
            ref={photoGalleryRef}
            refreshKey={refreshKey}
            onRefresh={refreshAll}
            activeMemory={activeMemory}
            onMemorySelect={handleMemorySelect}
          />
        </main>
      </div>

      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onRefresh={refreshAll}
        onScanStart={() => {
          setIsScanning(true)
          setScanProgress(0)
        }}
        isScanning={isScanning}
      />
    </>
  )
}

export default App