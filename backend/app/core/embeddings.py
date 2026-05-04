import numpy as np
import json
from app.models import Person

def best_similarity(person: Person, emb: np.ndarray) -> float:
    best = -1.0
    for enc in person.get_parsed_encodings():
        if enc.shape != emb.shape:
            continue
        denom = float(np.linalg.norm(enc)) * float(np.linalg.norm(emb))
        if denom > 0:
            best = max(best, float(np.dot(enc, emb) / denom))
    return best

def update_person_encoding(person: Person, emb: np.ndarray):
    if person.encoding:
        try:
            old_enc = np.array(json.loads(person.encoding), dtype=np.float32)
            new_enc = (old_enc + emb) / 2.0
            norm = np.linalg.norm(new_enc)
            if norm > 0:
                new_enc /= norm
            person.encoding = json.dumps(new_enc.tolist())
        except Exception:
            person.encoding = json.dumps(emb.tolist())
    else:
        person.encoding = json.dumps(emb.tolist())

    try:
        samples = json.loads(person.sample_encodings or "[]")
    except Exception:
        samples = []
    samples.append(emb.tolist())
    person.sample_encodings = json.dumps(samples[-5:])
