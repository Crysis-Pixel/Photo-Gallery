import { useState, useEffect, useRef, forwardRef, useImperativeHandle, createRef } from 'react'
import PhotoCard from './PhotoCard'
import '../styles/PhotoGallery.css'

const PhotoGallery = forwardRef(function PhotoGallery({ persons: personsProp, refreshKey, onRefresh }, ref) {
  const [photos, setPhotos] = useState([])
  const [totalPhotos, setTotalPhotos] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterCategory, setFilterCategory] = useState('')
  const [filterScenario, setFilterScenario] = useState('')
  const [filterPerson, setFilterPerson] = useState('')
  const [filterAlbum, setFilterAlbum] = useState('')
  const [currentPage, setCurrentPage] = useState(1)

  const [categories, setCategories] = useState([])
  const [scenarios, setScenarios] = useState([])
  const [albums, setAlbums] = useState([])

  const persons = personsProp || []

  const cardRefs = useRef({})

  useEffect(() => {
    photos.forEach(photo => {
      if (!cardRefs.current[photo.id]) {
        cardRefs.current[photo.id] = createRef()
      }
    })
  }, [photos])

  // ✅ REMOVED the separate useEffect that reset currentPage on filter change.
  // Page is now reset inline in each filter's onChange handler so the fetch
  // useEffect always sees currentPage=1 when a filter changes.

  useImperativeHandle(ref, () => ({
    scrollToPhoto: (photoId) => {
      setFilterCategory('')
      setFilterScenario('')
      setFilterPerson('')
      setFilterAlbum('')
      setCurrentPage(1)

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
    refresh: async () => {
      await fetchPhotos()
    }
  }))

  useEffect(() => {
    fetchMetadata()
  }, [])

  useEffect(() => {
    // If only refreshKey changed, do a silent fetch to avoid unmounting modals
    const isOnlyRefresh = refreshKey > 0
    fetchPhotos(isOnlyRefresh)
  }, [refreshKey])

  useEffect(() => {
    fetchPhotos(false) // Normal fetch for filter/page changes
  }, [currentPage, filterCategory, filterScenario, filterPerson, filterAlbum])

  const fetchMetadata = async () => {
    try {
      const response = await fetch(`http://${window.location.hostname}:8000/files/metadata`)
      if (response.ok) {
        const data = await response.json()
        setCategories(data.categories || [])
        setScenarios(data.scenarios || [])
        setAlbums(data.albums || [])
      }
    } catch (err) {
      console.error('Failed to fetch metadata:', err)
    }
  }

  const fetchPhotos = async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const params = new URLSearchParams()
      params.append('skip', (currentPage - 1) * 100)
      params.append('limit', 100)
      if (filterCategory) params.append('category', filterCategory)
      if (filterScenario) params.append('scenario', filterScenario)
      if (filterPerson) params.append('person_id', filterPerson)
      if (filterAlbum) params.append('album', filterAlbum)

      const response = await fetch(`http://${window.location.hostname}:8000/files/?${params.toString()}`)
      if (!response.ok) throw new Error('Failed to fetch photos')
      const data = await response.json()
      setPhotos(data.items || [])
      setTotalPhotos(data.total || 0)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handlePhotoUpdated = (updatedPhoto) => {
    setPhotos(prev => prev.map(p => p.id === updatedPhoto.id ? updatedPhoto : p))
  }

  const ITEMS_PER_PAGE = 100
  const totalPages = Math.ceil(totalPhotos / ITEMS_PER_PAGE)
  const paginatedPhotos = photos

  if (error) {
    return <div className="gallery-container"><div className="error-message">Error: {error}</div></div>
  }

  return (
    <div className="gallery-container">
      {/* Filters */}
      <div className="filters">
        <div className="filter-group">
          <label>Category:</label>
          <select
            value={filterCategory}
            onChange={e => { setCurrentPage(1); setFilterCategory(e.target.value) }}
          >
            <option value="">All Categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>Person:</label>
          <select
            value={filterPerson}
            onChange={e => { setCurrentPage(1); setFilterPerson(e.target.value) }}
          >
            <option value="">All Persons</option>
            {persons.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>Scenario:</label>
          <select
            value={filterScenario}
            onChange={e => { setCurrentPage(1); setFilterScenario(e.target.value) }}
          >
            <option value="">All Scenarios</option>
            {scenarios.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>Album:</label>
          <select
            value={filterAlbum}
            onChange={e => { setCurrentPage(1); setFilterAlbum(e.target.value) }}
          >
            <option value="">All Albums</option>
            {albums.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <button className="refresh-btn" onClick={fetchPhotos}>Refresh</button>
      </div>

      {loading ? (
        <div className="loading">Loading photos...</div>
      ) : (
        <>
          <div
            className="photo-count"
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}
          >
            <span>Showing {paginatedPhotos.length} of {totalPhotos} photos</span>
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
                  onRefresh={onRefresh}
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