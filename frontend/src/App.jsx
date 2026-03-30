import { useState, useRef } from 'react'
import './App.css'
import PhotoGallery from './components/PhotoGallery'
import PersonManager from './components/PersonManager'

function App() {
  // Lift persons state so PhotoGallery filter stays in sync after renames/merges
  const [persons, setPersons] = useState([])
  const photoGalleryRef = useRef(null)
  const scrollToPhoto = (photoId) => {
  photoGalleryRef.current?.scrollToPhoto(photoId)
}

  return (
    <div className="app">
      <header className="app-header">
        <h1>Photo Gallery</h1>
      </header>
      <main>
        <PersonManager onPersonsChange={setPersons} onPhotoClick={scrollToPhoto} />
        <PhotoGallery persons={persons} ref={photoGalleryRef} />
      </main>
    </div>
  )
}

export default App