import json
import numpy as np
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Person, Face, File
from app.core.embeddings import best_similarity, update_person_encoding
from app.utils import generate_random_color

def get_persons_with_covers(db: Session) -> List[Person]:
    persons = db.query(Person).all()
    
    # Subquery to count total faces in each file
    face_counts = (
        db.query(Face.file_id, func.count(Face.id).label('cnt'))
        .group_by(Face.file_id)
        .subquery()
    )

    for p in persons:
        # If we already have a persistent cover, skip calculation
        if p.cover_file_id:
            continue
            
        # Find the best face (from a photo with the fewest total faces)
        # If multiple photos have the same minimum count, pick one randomly.
        cover_face = (
            db.query(Face)
            .filter(Face.person_id == p.id)
            .join(face_counts, Face.file_id == face_counts.c.file_id)
            .order_by(face_counts.c.cnt.asc(), func.random())
            .first()
        )
        if cover_face:
            p.cover_file_id = cover_face.file_id
            db.add(p)
            
    try:
        db.commit()
    except Exception as e:
        print(f"Error persisting cover photos: {e}")
        db.rollback()
    return persons

def rename_person_record(db: Session, person_id: int, new_name: str) -> Optional[Person]:
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person: return None
    person.name = new_name
    db.query(File).filter(File.id.in_(db.query(Face.file_id).filter(Face.person_id == person_id))).update({File.person_name: new_name}, synchronize_session=False)
    db.commit()
    db.refresh(person)
    return person

def delete_person_record(db: Session, person_id: int) -> bool:
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person: return False
    db.query(Face).filter(Face.person_id == person_id).delete()
    db.delete(person)
    db.commit()
    return True

def create_new_person(db: Session, emb: np.ndarray) -> Person:
    def choose_color():
        used = {p.color for p in db.query(Person.color).filter(Person.color != None).all()}
        for _ in range(100):
            c = generate_random_color()
            if c not in used: return c
        return generate_random_color()
        
    p = Person(name="", color=choose_color(), encoding=json.dumps(emb.tolist()), sample_encodings=json.dumps([emb.tolist()]))
    db.add(p)
    db.flush()
    p.name = f"Person {p.id}"
    db.flush()
    return p

def merge_persons_records(db: Session, source_id: int, target_id: int) -> Optional[Person]:
    source = db.query(Person).filter(Person.id == source_id).first()
    target = db.query(Person).filter(Person.id == target_id).first()
    if not source or not target: return None
    
    db.query(Face).filter(Face.person_id == source_id).update({Face.person_id: target_id})
    db.query(File).filter(File.person_name == source.name).update({File.person_name: target.name})
    
    # Merge embeddings
    try:
        s_emb = np.array(json.loads(source.encoding))
        update_person_encoding(target, s_emb)
    except: pass
    
    target.cover_file_id = None # Force recalculation of best cover
    db.delete(source)
    db.commit()
    db.refresh(target)
    return target

def cleanup_orphaned_persons(db: Session):
    active_ids = {r[0] for r in db.query(Face.person_id).distinct().all()}
    orphaned = db.query(Person).filter(~Person.id.in_(active_ids)).all()
    for p in orphaned: db.delete(p)
    db.commit()
    return len(orphaned)

def auto_merge_unknown_persons(db: Session, sim_threshold: float = 0.60):
    named = db.query(Person).filter(~Person.name.ilike("Person %")).all()
    unnamed = db.query(Person).filter(Person.name.ilike("Person %")).all()
    merged_count = 0
    for u in unnamed:
        if not u.encoding: continue
        u_emb = np.array(json.loads(u.encoding))
        best_sim, best_target = -1.0, None
        for n in named:
            sim = best_similarity(n, u_emb)
            if sim > best_sim: best_sim, best_target = sim, n
        if best_sim >= sim_threshold:
            merge_persons_records(db, u.id, best_target.id)
            merged_count += 1
    return {"merged": merged_count}
