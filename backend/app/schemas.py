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

class FileResponse(FileBase):
    id: int
    created_at: datetime
    person_ids: List[int] = []
    person_names: List[str] = []
    person_colors: List[Optional[str]] = []

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
 
_apply_orm_mode(PersonResponse)
