"""Build the browser app in ui/web when its sources changed; the API serves ui/web/dist.

uv run --frozen python ops/web_build.py
"""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "ui" / "web"
SOURCES = ("src", "public", "index.html", "package.json", "package-lock.json", "vite.config.ts")


def _newest_source():
    files = []
    for name in SOURCES:
        path = WEB / name
        files.extend([path] if path.is_file() else [f for f in path.rglob("*") if f.is_file()])
    return max(f.stat().st_mtime for f in files)


def _manifest_current() -> bool:
    """Whether the UI plugins were last checked against the plugins installed now."""
    from msa.cli.plugin import UI_MANIFEST, ui_manifest

    if not UI_MANIFEST.is_file():
        return False
    return json.loads(UI_MANIFEST.read_text(encoding="utf-8")) == ui_manifest()


def ensure_built(say=print):
    index = WEB / "dist" / "index.html"
    # The build regenerates the manifest (npm prebuild); a plugin change on the server side
    # rebuilds too, so its UI plugins are checked against it.
    if index.is_file() and index.stat().st_mtime >= _newest_source() and _manifest_current():
        return
    npm = shutil.which("npm")
    if npm is None:
        if index.is_file():
            say("npm не найден: интерфейс не пересобран, используется прежняя сборка")
            return
        raise SystemExit("Для сборки интерфейса ui/web нужен Node.js 20 или новее (npm)")
    if not (WEB / "node_modules").is_dir():
        say("Интерфейс: устанавливаются зависимости (npm ci)")
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=WEB, check=True)
    say("Интерфейс: сборка")
    subprocess.run([npm, "run", "build"], cwd=WEB, check=True)


if __name__ == "__main__":
    ensure_built()
