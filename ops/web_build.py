"""Build the browser app in ui/web when its sources changed; the API serves ui/web/dist.

uv run --frozen python ops/web_build.py
"""

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


def ensure_built(say=print):
    index = WEB / "dist" / "index.html"
    if index.is_file() and index.stat().st_mtime >= _newest_source():
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
