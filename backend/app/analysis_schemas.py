from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AnalysisCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    language: str = Field(default="auto", min_length=1, max_length=40, pattern=r"^[\w-]+$")
    auto_summary: bool = False


class SummaryCreate(BaseModel):
    force: bool = False
    stream: bool = False


class ChatCreate(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    stream: bool = False


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1500)
    cue_ids: list[str] = Field(min_length=1, max_length=30)


class Chapter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    overview: str = Field(min_length=1, max_length=2000)
    cue_ids: list[str] = Field(min_length=1, max_length=50)
    points: list[Point] = Field(min_length=1, max_length=12)


class SummaryContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(min_length=1, max_length=300)
    overview: str = Field(min_length=1, max_length=4000)
    chapters: list[Chapter] = Field(min_length=1, max_length=40)


class AnswerContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=6000)
    cue_ids: list[str] = Field(default_factory=list, max_length=30)
    evidence: Literal["supported", "insufficient"]
