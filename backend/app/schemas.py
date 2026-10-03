from typing import Literal

from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class VideoFormat(BaseModel):
    format_id: str
    label: str
    ext: str | None = None
    resolution: str | None = None
    filesize: int | None = None
    fps: float | None = None


class ParseResponse(BaseModel):
    title: str
    extractor: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    formats: list[VideoFormat]


class DownloadRequest(ParseRequest):
    format_id: str = Field(default="best", min_length=1, max_length=80)
    delivery_mode: Literal["auto", "server", "redirect"] = "auto"


class DownloadCreated(BaseModel):
    task_id: str
    status: Literal["pending"]
    status_url: str
    download_url: str


class DownloadStatus(BaseModel):
    task_id: str
    status: Literal["pending", "processing", "ready", "failed"]
    delivery_mode: Literal["auto", "server", "redirect"]
    progress: float | None = None
    filename: str | None = None
    error: str | None = None
    expires_at: str