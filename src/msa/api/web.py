"""The browser interface: its built files and the settings it reads before sign-in.

The single-page app in ui/web is built into ui/web/dist and served from the API's own origin,
so the app and the API need no CORS between them.
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .problem import problem

router = APIRouter(tags=["ui"])

DEFAULT_DIST = Path(__file__).resolve().parents[3] / "ui" / "web" / "dist"
# Paths that never fall back to the app page: an unknown API path stays a JSON 404.
_NOT_PAGES = ("/v1/", "/docs", "/redoc", "/assets/")


@router.get("/v1/ui/config")
def config():
    """Role presets for the sign-in page. Set only in demo stacks through MSA_UI_DEMO_KEYS."""
    try:
        keys = json.loads(os.environ.get("MSA_UI_DEMO_KEYS", "{}"))
    except json.JSONDecodeError:
        keys = {}
    return {"demo_keys": keys if isinstance(keys, dict) else {}}


def mount(app):
    """Serve the built app when it exists; the API works the same without it."""
    dist = Path(os.environ.get("MSA_WEB_DIST", DEFAULT_DIST)).resolve()
    index = dist / "index.html"
    if not index.is_file():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="web-assets")

    @app.exception_handler(404)
    async def page(request, exc):
        path = request.url.path
        if request.method not in ("GET", "HEAD") or path == "/v1" or path.startswith(_NOT_PAGES):
            return problem(404, "Not Found", str(exc.detail), instance=path)
        # Files at the root of the build (favicon); every other path is a route of the app.
        file = (dist / path.lstrip("/")).resolve()
        if file.parent == dist and file.is_file():
            return FileResponse(file)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
