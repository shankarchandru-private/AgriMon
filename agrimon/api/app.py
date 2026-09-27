"""FastAPI application: JSON endpoints plus the static web pages."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agrimon.config import Settings
from agrimon.orchestrator.service import AgriMonService


class NewRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    scene_id: str


def create_app(settings: Settings, llm=None, service: AgriMonService | None = None) -> FastAPI:
    svc = service or AgriMonService(settings, llm=llm)
    app = FastAPI(title="AgriMon Evolution 1", version="0.1.0")
    app.state.service = svc

    @app.get("/api/health")
    def health():
        return svc.health()

    @app.get("/api/assets")
    def assets():
        return svc.catalog.model_dump()

    @app.get("/api/assets/{scene_id}/image")
    def asset_image(scene_id: str):
        try:
            return FileResponse(svc.scene_file(scene_id))
        except KeyError:
            raise HTTPException(404, "unknown scene")

    @app.post("/api/requests")
    def create_request(body: NewRequest):
        try:
            request_id = svc.submit(body.question, body.scene_id)
        except KeyError:
            raise HTTPException(404, "unknown scene")
        return {"request_id": request_id}

    @app.get("/api/requests/{request_id}")
    def get_request(request_id: str):
        record = svc.get_request(request_id)
        if record is None:
            raise HTTPException(404, "unknown request")
        return record.model_dump()

    @app.get("/api/capabilities")
    def capabilities():
        return svc.list_capabilities()

    @app.get("/api/capabilities/{cap_id}/{version}")
    def capability(cap_id: str, version: str):
        detail = svc.capability_detail(cap_id, version)
        if detail is None:
            raise HTTPException(404, "unknown capability")
        return detail

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        result = svc.get_run(run_id)
        if result is None:
            raise HTTPException(404, "unknown run")
        return result

    @app.get("/api/evaluations")
    def evaluations():
        return svc.list_evaluations()

    @app.get("/api/evaluations/{report_id}")
    def evaluation(report_id: str):
        report = svc.get_evaluation(report_id)
        if report is None:
            raise HTTPException(404, "unknown report")
        return report

    web: Path = settings.web_dir
    if web.exists():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app
