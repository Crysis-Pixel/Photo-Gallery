from pydantic import BaseModel
import pydantic
from typing import Optional, List
from datetime import datetime

# Detect Pydantic major version (v2 prefers `model_config`, v1 uses `Config.orm_mode`).
_pyd_ver = getattr(pydantic, "__version__", None) or getattr(pydantic, "VERSION", "1")
try:
    _pyd_major = int(str(_pyd_ver).split(".")[0])
except Exception:
    _pyd_major = 1
_PYDANTIC_V2 = _pyd_major >= 2


def _apply_orm_mode(cls):
    if _PYDANTIC_V2:
        setattr(cls, "model_config", {"from_attributes": True})
    else:
        class Config:
            orm_mode = True
        setattr(cls, "Config", Config)
    return cls

class FileBase(BaseModel):
    path: str
    file_type: str
    category: Optional[str] = None
    scenario: Optional[str] = None
    person_name: Optional[str] = None

class FileCreate(FileBase):
    auto_tag: Optional[bool] = False  

class FileUpdate(BaseModel):
    category: Optional[str] = None
    scenario: Optional[str] = None
    person_name: Optional[str] = None


class FilePersonAdd(BaseModel):
    person_id: Optional[int] = None
    person_name: Optional[str] = None

class FaceResponse(BaseModel):
    id: int
    person_id: Optional[int] = None
    person_name: Optional[str] = None
    person_color: Optional[str] = None
    box_left: Optional[float] = None
    box_top: Optional[float] = None
    box_width: Optional[float] = None
    box_height: Optional[float] = None

_apply_orm_mode(FaceResponse)

class FileResponse(FileBase):
    id: int
    created_at: datetime
    person_ids: List[int] = []
    person_names: List[str] = []
    person_colors: List[Optional[str]] = []
    faces: List[FaceResponse] = []
    face_scanned: bool = False
    live_video_id: Optional[int] = None
    is_hidden: bool = False
    
    # EXIF metadata
    date_taken: Optional[datetime] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    gps_altitude: Optional[float] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    location_name: Optional[str] = None

_apply_orm_mode(FileResponse)


class FolderConfigBase(BaseModel):
    path: str


class FolderConfigCreate(FolderConfigBase):
    pass


class FolderConfigResponse(FolderConfigBase):
    id: int
 
_apply_orm_mode(FolderConfigResponse)


class PersonBase(BaseModel):
    name: str


class PersonCreate(PersonBase):
    pass

class PersonUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class PersonResponse(PersonBase):
    id: int
    color: Optional[str] = None
    cover_photo_id: Optional[int] = None
    cover_photo_created_at: Optional[datetime] = None
 
_apply_orm_mode(PersonResponse)

class PaginatedFileResponse(BaseModel):
    items: List[FileResponse]
    total: int

class FilterMetadataResponse(BaseModel):
    categories: List[str]
    scenarios: List[str]
    albums: List[str]


class MemoryResponse(BaseModel):
    id: int
    title: str
    subtitle: Optional[str] = None
    memory_type: str
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    album_name: Optional[str] = None
    cover_file_id: Optional[int] = None
    preview_ids: Optional[str] = None
    photo_count: int = 0
    created_at: Optional[datetime] = None

_apply_orm_mode(MemoryResponse)
