import { useState } from 'react'
import './App.css'
import PhotoGallery from './components/PhotoGallery'
import PersonManager from './components/PersonManager'

function App() {
  // Lift persons state so PhotoGallery filter stays in sync after renames/merges
  const [persons, setPersons] = useState([])

  return (
    <div className="app">
      <header className="app-header">
        <h1>Photo Gallery</h1>
      </header>
      <main>
        <PersonManager onPersonsChange={setPersons} />
        <PhotoGallery persons={persons} />
      </main>
    </div>
  )
}

export default App