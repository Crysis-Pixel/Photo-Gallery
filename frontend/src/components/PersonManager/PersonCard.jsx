const API = `http://${window.location.hostname}:8000/files`

export default function PersonCard({ person, isSource, mergeSource, isExpanded, loadingPhotos, onRemove, onEdit, onMerge, onSeePhotos, children }) {
  return (
    <div className={`pm-card ${isSource ? 'pm-card--source' : ''} ${mergeSource && !isSource ? 'pm-card--merge-target' : ''}`}>
      <button className="pm-card-remove-btn" onClick={() => onRemove(person.id)} title="Remove person">✕</button>
      
      <div className="pm-avatar">
        {person.cover_photo_id ? (
          <img src={`${API}/${person.cover_photo_id}/thumbnail`} alt={person.name} className="pm-avatar-img" />
        ) : (
          <span className="pm-avatar-icon">👤</span>
        )}
      </div>

      <div className="pm-name-row">
        <span className="pm-name">{person.name}</span>
        <button className="pm-icon-btn" title="Rename" onClick={() => onEdit(person.id, person.name)}>✏️</button>
      </div>

      <div className="pm-actions">
        <button className="pm-btn pm-btn-sm" onClick={() => onSeePhotos(person.id)} disabled={loadingPhotos[person.id]}>
          {loadingPhotos[person.id] ? '…' : isExpanded ? 'Hide photos' : 'See photos'}
        </button>

        {mergeSource && !isSource ? (
          <button className="pm-btn pm-btn-sm pm-btn-merge" onClick={() => onMerge(person.id)}>← Merge into</button>
        ) : !mergeSource ? (
          <button className="pm-btn pm-btn-sm pm-btn-ghost" onClick={() => onMerge(person.id, true)}>🔗 Merge</button>
        ) : null}
      </div>

      {isExpanded && children}
    </div>
  )
}
