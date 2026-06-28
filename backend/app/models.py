from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, Boolean, UniqueConstraint
import sqlalchemy
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime
from typing import Optional


class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, unique=True, index=True)
    file_type = Column(String, index=True)  # photo, document, screenshot
    category = Column(String, nullable=True)
    scenario = Column(String, nullable=True)
    person_name = Column(String, nullable=True)
    face_scanned = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Live Photos
    live_video_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    is_hidden = Column(Boolean, default=False, index=True)

    # EXIF metadata
    date_taken = Column(DateTime, nullable=True, index=True)
    gps_latitude = Column(Float, nullable=True)
    gps_longitude = Column(Float, nullable=True)
    gps_altitude = Column(Float, nullable=True)
    camera_make = Column(String, nullable=True)
    camera_model = Column(String, nullable=True)
    location_name = Column(String, nullable=True, index=True)

    faces = relationship("Face", back_populates="file", cascade="all, delete-orphan")

    @property
    def person_ids(self):
        if not self.faces:
            return []
        faces = sorted(self.faces, key=lambda f: f.id)
        return [f.person_id for f in faces if f.person_id is not None]

    @property
    def person_names(self):
        if not self.faces:
            return []
        faces = sorted(self.faces, key=lambda f: f.id)
        names = []
        for f in faces:
            if f.person_id is None:
                continue
            if f.person and f.person.name:
                names.append(f.person.name)
            else:
                names.append(f"Person {f.person_id}")
        return names

    @property
    def person_colors(self):
        from app.utils import get_default_person_color
        if not self.faces:
            return []
        faces = sorted(self.faces, key=lambda f: f.id)
        colors = []
        for f in faces:
            if f.person_id is None:
                colors.append("#e8d5b0") # Unknown/default accent
                continue
            if f.person and f.person.color:
                colors.append(f.person.color)
            else:
                colors.append(get_default_person_color(f.person_id))
        return colors


class Person(Base):
    __tablename__ = "persons"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=True)
    color = Column(String, nullable=True)
    # Stored as a JSON list (string) of floats representing a face embedding
    encoding = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    sample_encodings = Column(Text, nullable=True)  # JSON list of up to 5 embeddings
    cover_file_id = Column(Integer, nullable=True)
    faces = relationship("Face", back_populates="person")
    cover_file = relationship("File", foreign_keys=[cover_file_id], primaryjoin="Person.cover_file_id == File.id")

    @property
    def cover_photo_id(self):
        return self.cover_file_id

    @property
    def cover_photo_created_at(self):
        return self.cover_file.created_at if self.cover_file else None

    _parsed_encodings = None
    _last_encoding = None
    _last_sample_encodings = None

    def get_parsed_encodings(self):
        import json
        import numpy as np
        if self._parsed_encodings is None or self.encoding != self._last_encoding or self.sample_encodings != self._last_sample_encodings:
            encs = []
            if self.encoding:
                try:
                    encs.append(np.array(json.loads(self.encoding), dtype=np.float32))
                except Exception:
                    pass
            if self.sample_encodings:
                try:
                    for s in json.loads(self.sample_encodings)[:5]:
                        encs.append(np.array(s, dtype=np.float32))
                except Exception:
                    pass
            self._parsed_encodings = encs
            self._last_encoding = self.encoding
            self._last_sample_encodings = self.sample_encodings
        return self._parsed_encodings


class Face(Base):
    __tablename__ = "faces"
    __table_args__ = (
        # Prevent multiple tagging of the same person to the same file
        sqlalchemy.UniqueConstraint('file_id', 'person_id', name='unique_file_person'),
    )

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"), index=True)
    person_id = Column(Integer, ForeignKey("persons.id"), index=True)
    
    # Bounding box coordinates stored as relative percentages [0.0 - 1.0]
    box_left = Column(Float, nullable=True)
    box_top = Column(Float, nullable=True)
    box_width = Column(Float, nullable=True)
    box_height = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("File", back_populates="faces")
    person = relationship("Person", back_populates="faces")

    @property
    def person_name(self):
        return self.person.name if self.person else None

    @property
    def person_color(self):
        from app.utils import get_default_person_color
        if self.person and self.person.color:
            return self.person.color
        return get_default_person_color(self.person_id)


class FolderConfig(Base):
    __tablename__ = "folder_config"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, unique=True, index=True)


class Memory(Base):
    """Auto-generated memory grouping based on location, time, and album."""
    __tablename__ = "memories"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    subtitle = Column(String, nullable=True)       # e.g. "Jun 18–22, 2024"
    memory_type = Column(String, index=True)       # "location", "album", "time"
    location_name = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    album_name = Column(String, nullable=True)
    cover_file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    preview_ids = Column(String, nullable=True)  # Comma-separated list of file IDs
    photo_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    cover_file = relationship("File", foreign_keys=[cover_file_id],
                              primaryjoin="Memory.cover_file_id == File.id")