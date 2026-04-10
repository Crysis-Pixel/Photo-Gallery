import { useState, useRef } from 'react'
import './App.css'
import PhotoGallery from './components/PhotoGallery'
import PersonManager from './components/PersonManager'
import Sidebar from './components/Sidebar'

function App() {
  const [persons, setPersons] = useState([])
  const [refreshKey, setRefreshKey] = useState(0)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const photoGalleryRef = useRef(null)

  const scrollToPhoto = (photoId) => {
    photoGalleryRef.current?.scrollToPhoto(photoId)
  }

  const refreshAll = () => {
    setRefreshKey(prev => prev + 1)
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