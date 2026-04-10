from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime


class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, unique=True, index=True)
    file_type = Column(String, index=True)  # photo, document, screenshot
    category = Column(String, nullable=True)
    scenario = Column(String, nullable=True)
    person_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    faces = relationship("Face", back_populates="file")

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
        if not self.faces:
            return []
        faces = sorted(self.faces, key=lambda f: f.id)
        colors = []
        for f in faces:
            if f.person_id is None:
                continue
            if f.person and f.person.color:
                colors.append(f.person.color)
            else:
                colors.append(None)
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
    faces = relationship("Face", back_populates="person")


class Face(Base):
    __tablename__ = "faces"

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
        return self.person.color if self.person else None


class FolderConfig(Base):
    __tablename__ = "folder_config"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, unique=True, index=True)