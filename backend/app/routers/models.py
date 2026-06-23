from fastapi import APIRouter
from app.core import ai
import app.core.model_downloader as model_downloader

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("/status")
def get_model_status():
    report = ai.status_report()
    report["download_in_progress"] = model_downloader.download_in_progress
    return report
