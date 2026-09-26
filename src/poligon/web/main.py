# Poligon — web UI (FastAPI) and launcher.
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
"""
Poligon web — thin HTTP wrapper over generate().
No generation logic lives here. All logic is in poligon.core.
"""
from __future__ import annotations

import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import poligon.core.generate as gen_mod
from poligon.core.generate import generate  # NEVER from poligon.core import generate
from poligon.core.history import load_history

PORT = 7333
HOST = "127.0.0.1"
HISTORY_LIMIT = 20

# generate() seeds the one module-level random stream; serialise calls so
# concurrent requests cannot interleave draws and break reproducibility.
_GENERATE_LOCK = threading.Lock()


class GenerateRequest(BaseModel):
    template: str
    seed: int
    difficulty: int = 1


def static_dir() -> Path:
    """Static assets dir — inside the PyInstaller bundle when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "poligon" / "web" / "static"
    return Path(__file__).resolve().parent / "static"


def _download_url(scenario_id: str) -> str:
    return f"/api/download/{scenario_id}"


def create_app() -> FastAPI:
    app = FastAPI(title="Poligon", docs_url=None, redoc_url=None)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir() / "index.html",
                            media_type="text/html")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "port": PORT}

    @app.post("/api/generate")
    def generate_challenge(req: GenerateRequest) -> dict:
        try:
            with _GENERATE_LOCK:
                result = generate(req.template, req.difficulty, req.seed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {**result, "download_url": _download_url(result["scenario_id"])}

    @app.get("/api/download/{scenario_id}")
    def download(scenario_id: str) -> FileResponse:
        try:
            canonical = str(uuid.UUID(scenario_id))
        except ValueError as exc:
            raise HTTPException(status_code=404,
                                detail="Unknown scenario") from exc
        zip_path = Path(gen_mod.DEFAULT_OUTPUT_DIR) / canonical / "challenge.zip"
        if not zip_path.is_file():
            raise HTTPException(status_code=404, detail="Unknown scenario")
        return FileResponse(zip_path, media_type="application/zip",
                            filename=f"poligon_{canonical}.zip")

    @app.get("/api/history")
    def history() -> list[dict]:
        return [{**entry, "download_url": _download_url(entry["scenario_id"])}
                for entry in load_history()[:HISTORY_LIMIT]]

    return app


def main() -> None:
    """Start uvicorn on HOST:PORT in a thread and open the browser."""
    config = uvicorn.Config(create_app(), host=HOST, port=PORT,
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() \
            and time.monotonic() < deadline:
        time.sleep(0.05)
    if server.started:
        webbrowser.open(f"http://{HOST}:{PORT}")

    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
