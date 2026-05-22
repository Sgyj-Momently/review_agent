"""FastAPI entrypoint for the review agent."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator

from .reviewer import review_document

app = FastAPI(title="Review Agent API", version="0.1.0")

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


class ReviewRequest(BaseModel):
    project_id: str = Field(min_length=1)
    styled_markdown: str
    target_keywords: str | None = None
    photos: list[dict[str, Any]] = Field(default_factory=list)
    excluded_photos: list[dict[str, Any]] = Field(default_factory=list)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "review_agent"}


@app.post("/api/v1/reviews")
def create_review(request: ReviewRequest) -> dict[str, Any]:
    return {"project_id": request.project_id, **review_document(request.model_dump())}

