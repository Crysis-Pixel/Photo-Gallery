import { useState, useEffect, useRef, forwardRef, useImperativeHandle, createRef } from 'react'
import PhotoCard from './PhotoCard'
import '../styles/PhotoGallery.css'

const PhotoGallery = forwardRef(function PhotoGallery({ persons: personsProp, refreshKey }, ref) {
  const [photos, setPhotos] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterCategory, setFilterCategory] = useState('')
  const [filterScenario, setFilterScenario] = useState('')
  const [filterPerson, setFilterPerson] = useState('')
  const [filterAlbum, setFilterAlbum] = useState('')
  const [currentPage, setCurrentPage] = useState(1)

  const persons = personsProp || []

  // Refs for scrolling
  const cardRefs = useRef({})

  useEffect(() => {
    photos.forEach(photo => {
      if (!cardRefs.current[photo.id]) {
        cardRefs.current[photo.id] = createRef()
      }
    })
  }, [photos])

  useEffect(() => {
    setCurrentPage(1)
  }, [filterCategory, filterScenario, filterPerson, filterAlbum])

  useImperativeHandle(ref, () => ({
    scrollToPhoto: (photoId) => {
      setFilterCategory('')
      setFilterScenario('')
      setFilterPerson('')
      setFilterAlbum('')

      setTimeout(() => {
        const cardRef = cardRefs.current[photoId]
        if (cardRef?.current) {
          cardRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
          cardRef.current.classList.add('photo-card--highlight')
          setTimeout(() => cardRef.current?.classList.remove('photo-card--highlight'), 1800)
          setTimeout(() => cardRef.current?.click(), 400)
        }
      }, 100)
    },
    refresh: async () => {          // ← NEW
      await fetchPhotos()
    }
  }))

  // Data fetching
  useEffect(() => {
    fetchPhotos()
  }, [refreshKey])

  const fetchPhotos = async () => {
    try {
      setLoading(true)
      const response = await fetch('http://localhost:8000/files/')
      if (!response.ok) throw new Error('Failed to fetch photos')
      const data = await response.json()
      setPhotos(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handlePhotoUpdated = (updatedPhoto) => {
    setPhotos(prev => prev.map(p => p.id === updatedPhoto.id ? updatedPhoto : p));
  }

  const getUniqueCategories = () => Array.from(new Set(photos.map(p => p.category).filter(Boolean))).sort()
  const getUniqueScenarios = () => Array.from(new Set(photos.map(p => p.scenario).filter(Boolean)))

  const getAlbumName = (path) => {
    if (!path) return 'Unknown'
    const parts = path.split(/[\\/]/)
    return parts.length > 1 ? parts[parts.length - 2] : 'Unknown'
  }
  const getUniqueAlbums = () => Array.from(new Set(photos.map(p => getAlbumName(p.path)))).sort()

  const filteredPhotos = photos.filter(photo => {
    const categoryMatch = !filterCategory || photo.category === filterCategory
    const scenarioMatch = !filterScenario || photo.scenario === filterScenario
    const personMatch = !filterPerson || (Array.isArray(photo.person_ids) && photo.person_ids.includes(Number(filterPerson)))
    const albumMatch = !filterAlbum || getAlbumName(photo.path) === filterAlbum
    return categoryMatch && scenarioMatch && personMatch && albumMatch
  })

  const ITEMS_PER_PAGE = 100;
  const totalPages = Math.ceil(filteredPhotos.length / ITEMS_PER_PAGE);
  const paginatedPhotos = filteredPhotos.slice((currentPage - 1) * ITEMS_PER_PAGE, currentPage * ITEMS_PER_PAGE);

  if (error) {
    return <div className="gallery-container"><div className="error-message">Error: {error}</div></div>
  }

  return (
    <div className="gallery-container">
      {/* Filters */}
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
        <div className="filter-group">
          <label>Album:</label>
          <select value={filterAlbum} onChange={e => setFilterAlbum(e.target.value)}>
            <option value="">All Albums</option>
            {getUniqueAlbums().map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <button className="refresh-btn" onClick={fetchPhotos}>Refresh</button>
      </div>

      {loading ? (
        <div className="loading">Loading photos...</div>
      ) : (
        <>
          <div className="photo-count" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <span>Showing {paginatedPhotos.length} of {filteredPhotos.length} photos</span>
            {totalPages > 1 && (
              <div className="pagination-controls">
                <button 
                  className="pagination-btn"
                  onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
                  disabled={currentPage === 1}
                >
                  Prev
                </button>
                <div className="pagination-select-wrapper">
                  <span>Page</span>
                  <select 
                    className="page-select"
                    value={currentPage}
                    onChange={e => setCurrentPage(Number(e.target.value))}
                  >
                    {Array.from({ length: totalPages }, (_, i) => i + 1).map(page => (
                      <option key={page} value={page}>{page}</option>
                    ))}
                  </select>
                  <span>of {totalPages}</span>
                </div>
                <button 
                  className="pagination-btn"
                  onClick={() => setCurrentPage(prev => Math.min(totalPages, prev + 1))}
                  disabled={currentPage === totalPages}
                >
                  Next
                </button>
              </div>
            )}
          </div>
          <div className="gallery-grid">
            {paginatedPhotos.length > 0 ? (
              paginatedPhotos.map(photo => (
                <PhotoCard
                  key={photo.id}
                  photo={photo}
                  cardRef={cardRefs.current[photo.id]}
                  onPhotoUpdated={handlePhotoUpdated}
                />
              ))
            ) : (
              <div className="no-photos">No photos found</div>
            )}
          </div>
        </>
      )}
    </div>
  )
})

export default PhotoGallery