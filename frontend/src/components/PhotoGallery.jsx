import { useState, useEffect, useRef, forwardRef, useImperativeHandle, createRef } from 'react'
import PhotoCard from './PhotoCard'
import '../styles/PhotoGallery.css'
import { BASE_URL } from '../api'

const PhotoGallery = forwardRef(function PhotoGallery({ persons: personsProp, refreshKey, onRefresh }, ref) {
  const [photos, setPhotos] = useState([])
  const [totalPhotos, setTotalPhotos] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterCategory, setFilterCategory] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState('')
  const [filterPerson, setFilterPerson] = useState('')
  const [filterAlbum, setFilterAlbum] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [showScrollTop, setShowScrollTop] = useState(false)

  const [categories, setCategories] = useState([])
  const [scenarios, setScenarios] = useState([])
  const [albums, setAlbums] = useState([])

  useEffect(() => {
    // In Tauri WebView, scroll happens on document.documentElement, not window
    const handleScroll = () => {
      const scrollY = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop
      setShowScrollTop(scrollY > 300)
    }
    window.addEventListener('scroll', handleScroll, { passive: true })
    document.addEventListener('scroll', handleScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', handleScroll)
      document.removeEventListener('scroll', handleScroll)
    }
  }, [])


  // Track photo IDs that were updated locally (via modal) so that a concurrent
  // silent refresh doesn't clobber the fresh data with a potentially stale
  // server response (SQLAlchemy identity map may return cached faces after rescan).
  const locallyUpdatedRef = useRef(new Set())

  const persons = personsProp || []
  const sortedPersons = [...persons].sort((a, b) => {
    const aIsUnnamed = a.name.startsWith('Person ');
    const bIsUnnamed = b.name.startsWith('Person ');
    if (aIsUnnamed && !bIsUnnamed) return 1;
    if (!aIsUnnamed && bIsUnnamed) return -1;
    return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
  });

  const cardRefs = useRef({})

  const getCardRef = (photoId) => {
    if (!cardRefs.current[photoId]) {
      cardRefs.current[photoId] = createRef()
    }
    return cardRefs.current[photoId]
  }

  useImperativeHandle(ref, () => ({
    scrollToPhoto: async (photoId) => {
      // Blur active element immediately to release horizontal scroll-snapping focus locks
      if (document.activeElement) {
        document.activeElement.blur()
      }

      let targetPage = 1
      try {
        const res = await fetch(`${BASE_URL}/files/?limit=10000`)
        if (res.ok) {
          const data = await res.json()
          const items = data.items || []
          const index = items.findIndex(item => item.id === photoId)
          if (index !== -1) {
            targetPage = Math.floor(index / 52) + 1
          }
        }
      } catch (err) {
        console.error('Failed to resolve photo page:', err)
      }

      setFilterCategory('')
      setSearchTerm('')
      setFilterPerson('')
      setFilterAlbum('')
      setCurrentPage(targetPage)

      const tryScroll = (attempts = 0) => {
        const cardRef = cardRefs.current[photoId]
        if (cardRef?.current) {
          const rect = cardRef.current.getBoundingClientRect()
          // Wait if card hasn't been laid out by the browser yet
          if (rect.height === 0) {
            if (attempts < 30) {
              setTimeout(() => tryScroll(attempts + 1), 100)
            }
            return
          }

          // Blur active element to release any horizontal scroll-snapping focus locks
          if (document.activeElement) {
            document.activeElement.blur()
          }

          // Activate browser scroll engine if never scrolled before
          const currentScroll = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop
          if (currentScroll === 0) {
            window.scrollTo(0, 1)
            try { document.documentElement.scrollTo(0, 1) } catch { }
          }

          const scrollTop = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop
          const targetY = rect.top + scrollTop - (window.innerHeight / 2) + (rect.height / 2)

          window.scrollTo({ top: targetY, behavior: 'smooth' })
          try {
            document.documentElement.scrollTo({ top: targetY, behavior: 'smooth' })
          } catch { }

          cardRef.current.classList.add('photo-card--highlight')
          setTimeout(() => cardRef.current?.classList.remove('photo-card--highlight'), 1500)
        } else if (attempts < 30) {
          setTimeout(() => tryScroll(attempts + 1), 100)
        }
      }
      setTimeout(() => tryScroll(), 300)
    },
    filterByPersonAndScroll: async (personId, photoId) => {
      // Blur active element immediately to release horizontal scroll-snapping focus locks
      if (document.activeElement) {
        document.activeElement.blur()
      }

      let targetPage = 1
      try {
        // Fetch all photos of this person to determine the correct page index of the clicked photo
        const res = await fetch(`${BASE_URL}/files/?person_id=${personId}&limit=10000`)
        if (res.ok) {
          const data = await res.json()
          const items = data.items || []
          const index = items.findIndex(item => item.id === photoId)
          if (index !== -1) {
            targetPage = Math.floor(index / 52) + 1
          }
        }
      } catch (err) {
        console.error('Failed to resolve photo page:', err)
      }

      setFilterCategory('')
      setSearchTerm('')
      setFilterAlbum('')
      setFilterPerson(String(personId))
      setCurrentPage(targetPage)

      // Immediately scroll down to the gallery container to show user feedback and release scroll locks
      setTimeout(() => {
        const galleryEl = document.querySelector('.gallery-container')
        if (galleryEl) {
          const rect = galleryEl.getBoundingClientRect()
          const scrollTop = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop
          const targetY = rect.top + scrollTop - 130
          window.scrollTo({ top: targetY, behavior: 'smooth' })
          try {
            document.documentElement.scrollTo({ top: targetY, behavior: 'smooth' })
          } catch { }
        }
      }, 50)

      // Wait for the filtered data to load, then scroll to the photo
      const tryScroll = (attempts = 0) => {
        const cardRef = cardRefs.current[photoId]
        if (cardRef?.current) {
          const rect = cardRef.current.getBoundingClientRect()
          // Wait if card hasn't been laid out by the browser yet
          if (rect.height === 0) {
            if (attempts < 30) {
              setTimeout(() => tryScroll(attempts + 1), 100)
            }
            return
          }

          // Blur active element again just in case focus was reclaimed
          if (document.activeElement) {
            document.activeElement.blur()
          }

          const scrollTop = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop
          const targetY = rect.top + scrollTop - (window.innerHeight / 2) + (rect.height / 2)

          window.scrollTo({ top: targetY, behavior: 'smooth' })
          try {
            document.documentElement.scrollTo({ top: targetY, behavior: 'smooth' })
          } catch { }

          cardRef.current.classList.add('photo-card--highlight')
          setTimeout(() => cardRef.current?.classList.remove('photo-card--highlight'), 1500)
        } else if (attempts < 30) {
          setTimeout(() => tryScroll(attempts + 1), 100)
        }
      }
      setTimeout(() => tryScroll(), 300)
    },
    refresh: async () => {
      await fetchPhotos()
    }
  }))

  useEffect(() => {
    fetchPhotos(refreshKey > 0)
    fetchMetadata()
  }, [refreshKey])

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchTerm(searchTerm)
    }, 500)
    return () => clearTimeout(timer)
  }, [searchTerm])

  useEffect(() => {
    fetchPhotos(false)
  }, [currentPage, filterCategory, debouncedSearchTerm, filterPerson, filterAlbum])

  const fetchMetadata = async () => {
    try {
      const response = await fetch(`${BASE_URL}/files/metadata`)
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
      params.append('skip', (currentPage - 1) * 52)
      params.append('limit', 52)
      if (filterCategory) params.append('category', filterCategory)
      if (debouncedSearchTerm) params.append('search', debouncedSearchTerm)
      if (filterPerson) params.append('person_id', filterPerson)
      if (filterAlbum) params.append('album', filterAlbum)

      const response = await fetch(`${BASE_URL}/files/?${params.toString()}`)
      if (!response.ok) throw new Error('Failed to fetch photos')

      const data = await response.json()
      const incoming = data.items || []

      setPhotos(prev => {
        // For any photo that was locally updated since the last full fetch,
        // keep our fresh copy instead of the server's potentially-stale one.
        const localMap = new Map()
        if (locallyUpdatedRef.current.size > 0) {
          prev.forEach(p => {
            if (locallyUpdatedRef.current.has(p.id)) localMap.set(p.id, p)
          })
        }

        const merged = incoming.map(serverPhoto =>
          localMap.has(serverPhoto.id) ? localMap.get(serverPhoto.id) : serverPhoto
        )

        // Clear protection only on a full (non-silent) fetch — those are
        // triggered by real user actions like page change or filter, at which
        // point the server data is authoritative again.
        if (!silent) locallyUpdatedRef.current.clear()

        return merged
      })

      setTotalPhotos(data.total || 0)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Called by PhotoModal when a photo is edited/rescanned.
  // Patches the card immediately AND marks the ID as locally-updated so the
  // next silent refresh doesn't overwrite it with a potentially stale response.
  const handlePhotoUpdated = (updatedPhoto) => {
    locallyUpdatedRef.current.add(updatedPhoto.id)
    setPhotos(prev => prev.map(p => p.id === updatedPhoto.id ? updatedPhoto : p))
  }

  // Silent background re-fetch — keeps counts/filters accurate without
  // flashing the loading state or closing any open modal.
  const handleSilentRefresh = () => {
    fetchPhotos(true)
  }

  const ITEMS_PER_PAGE = 52
  const totalPages = Math.ceil(totalPhotos / ITEMS_PER_PAGE)
  const paginatedPhotos = photos

  if (error) {
    return <div className="gallery-container"><div className="error-message">Error: {error}</div></div>
  }

  const scrollToTop = () => {
    try { window.scrollTo({ top: 0, behavior: 'smooth' }) } catch { }
    try { document.documentElement.scrollTo({ top: 0, behavior: 'smooth' }) } catch { }
    try { document.body.scrollTo({ top: 0, behavior: 'smooth' }) } catch { }
  }

  return (
    <div className="gallery-container">
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
            {sortedPersons.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <label>Search:</label>
          <input
            type="text"
            placeholder="Search albums or descriptions..."
            value={searchTerm}
            onChange={e => { setCurrentPage(1); setSearchTerm(e.target.value) }}
            className="search-input"
          />
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
        <button className="refresh-btn" onClick={() => { fetchPhotos(false); onRefresh?.() }}>Refresh</button>
      </div>

      <div className="gallery-content-wrapper" style={{ position: 'relative', minHeight: '300px' }}>
        {loading && (
          <div className="loading" style={{
            position: 'absolute',
            inset: 0,
            background: 'rgba(7, 7, 15, 0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
            backdropFilter: 'blur(6px)',
            borderRadius: 'var(--radius-xl)',
            fontSize: '1rem',
            color: 'var(--accent)',
            fontWeight: 500,
            letterSpacing: '0.05em'
          }}>
            Loading photos...
          </div>
        )}
        <div style={{ opacity: loading ? 0.35 : 1, transition: 'opacity 0.25s ease' }}>
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
                  cardRef={getCardRef(photo.id)}
                  onPhotoUpdated={handlePhotoUpdated}
                  onRefresh={handleSilentRefresh}
                />
              ))
            ) : (
              <div className="no-photos">No photos found</div>
            )}
          </div>

          {totalPages > 1 && (
            <div className="pagination-footer">
              <div className="pagination-controls">
                <button
                  className="pagination-btn"
                  onClick={() => { setCurrentPage(prev => Math.max(1, prev - 1)); scrollToTop() }}
                  disabled={currentPage === 1}
                >
                  Prev
                </button>
                <div className="pagination-select-wrapper">
                  <span>Page</span>
                  <select
                    className="page-select"
                    value={currentPage}
                    onChange={e => { setCurrentPage(Number(e.target.value)); scrollToTop() }}
                  >
                    {Array.from({ length: totalPages }, (_, i) => i + 1).map(page => (
                      <option key={page} value={page}>{page}</option>
                    ))}
                  </select>
                  <span>of {totalPages}</span>
                </div>
                <button
                  className="pagination-btn"
                  onClick={() => { setCurrentPage(prev => Math.min(totalPages, prev + 1)); scrollToTop() }}
                  disabled={currentPage === totalPages}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Scroll-to-top: always in DOM so CSS transition works; positioned fixed bottom-right */}
      <button
        className={`scroll-to-top${showScrollTop ? ' scroll-to-top--visible' : ''}`}
        onClick={scrollToTop}
        aria-label="Scroll to top"
        tabIndex={showScrollTop ? 0 : -1}
      >
        ↑
      </button>
    </div>
  )
})

export default PhotoGallery