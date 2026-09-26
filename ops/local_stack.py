"""Native stack without Docker: PostgreSQL and the API that serves the browser app.

One interface: the browser app at http://127.0.0.1:8091 — event text, graph review,
Track A v3.2 calculation, portfolio, report, approval, and the analyst's own portfolios.

The language model is one profile, chosen at start:

- ``deepseek`` (default) — the external DeepSeek API; key from DEEPSEEK_API_KEY, handed to
  the API process in memory and never written. External, so runs use demo portfolios only.
- ``local`` — any OpenAI-compatible server on this host, LM Studio by default
  (MSA_LLM_BASE_URL, http://127.0.0.1:1234/v1); the loaded model is read from its /models.
- ``mock`` — no model: graphs come from fixtures, the calculation is real.

    uv run --frozen python ops/local_stack.py up [deepseek|local|mock]
    uv run --frozen python ops/local_stack.py down|status|logs [name]
"""

import hashlib
import io
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import webbrowser
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ops"))

from check_services import check_llm  # noqa: E402
from init_env import DATABASE as PLATFORM_DATABASE  # noqa: E402
from init_env import init_env  # noqa: E402
from web_build import ensure_built  # noqa: E402

DATA = ROOT / ".data"
LOGS, RUN = DATA / "logs", DATA / "run"
# initdb on Windows breaks on a non-ASCII path (it copies share files by path in UTF-8):
# under such a checkout the cluster and binaries live in the user's local app data.
# The cluster is this checkout's own: another MacroStress checkout keeps its data apart.
PG_ROOT = DATA if str(DATA).isascii() else Path(os.getenv("LOCALAPPDATA", "")) / "msa-core-local"
PG_DATA, PG_HOME = PG_ROOT / "pg", PG_ROOT / "pgsql"
# PostgreSQL 16.2 binaries from the pgserver wheel, pinned by hash; elsewhere from PATH.
PG_WHEEL = (
    "https://files.pythonhosted.org/packages/85/80/"
    "f6304274c1740c283bc7317ababceb3c23c8275ce4995f7379e17b49bc6d/"
    "pgserver-0.1.4-cp312-cp312-win_amd64.whl",
    "406e9355334e40754160a33d93f18a848720a38cd0b68da50be2ea272c89ed2d",
)
DEEPSEEK_URL, DEEPSEEK_MODEL = "https://api.deepseek.com/v1", "deepseek-flash"
LOCAL_URL = "http://127.0.0.1:1234/v1"  # LM Studio's default server.
# 5433 and 8091: another checkout may hold 5432 and 8090. The API is not on 8080, which backup
# agents on Windows hosts often hold.
PORTS = {"postgres": 5433, "api": 8091}
API = f"http://127.0.0.1:{PORTS['api']}"
HEALTH = {"api": f"{API}/v1/openapi.json"}


def say(text):
    print(text, flush=True)


def env_file():
    values = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = value.strip("'")
    return values


def child_env(extra):
    # The DeepSeek key reaches only the API, under the name the LLM client reads.
    env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
    return {**env, **extra}


# PostgreSQL -------------------------------------------------------------------------


def pg_bin(name):
    if sys.platform != "win32":
        return name
    path = PG_HOME / "pgserver" / "pginstall" / "bin" / f"{name}.exe"
    if not path.exists():
        say("Скачиваю PostgreSQL 16 (pgserver, ~40 МБ)…")
        url, expected = PG_WHEEL
        with urlopen(url, timeout=300) as response:
            wheel = response.read()
        if hashlib.sha256(wheel).hexdigest() != expected:
            raise SystemExit("PostgreSQL: контрольная сумма архива не совпала")
        with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
            members = [m for m in archive.namelist() if m.startswith("pgserver/pginstall/")]
            archive.extractall(PG_HOME, members)
    return str(path)


def pg_running():
    result = subprocess.run([pg_bin("pg_ctl"), "-D", str(PG_DATA), "status"], capture_output=True)
    return result.returncode == 0


def pg_up(password):
    fresh = not (PG_DATA / "PG_VERSION").exists()
    if fresh:
        say(f"PostgreSQL: первый запуск, создаю кластер в {PG_DATA}")
        RUN.mkdir(parents=True, exist_ok=True)
        pwfile = RUN / f"pw-{secrets.token_hex(4)}"
        pwfile.write_text(password)
        try:
            subprocess.run(
                [
                    pg_bin("initdb"),
                    "-D",
                    str(PG_DATA),
                    "-U",
                    "msa",
                    "-A",
                    "scram-sha-256",
                    f"--pwfile={pwfile}",
                    "-E",
                    "UTF8",
                    "--locale=C",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        finally:
            pwfile.unlink()
    if not pg_running():
        busy("postgres")
        subprocess.run(
            [
                pg_bin("pg_ctl"),
                "-D",
                str(PG_DATA),
                "-l",
                str(LOGS / "postgres.log"),
                "-o",
                f"-p {PORTS['postgres']} -h 127.0.0.1",
                "-w",
                "start",
            ],
            check=True,
            # The server inherits these handles; a pipe would stay open for its lifetime.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    # Also on reruns: a first start interrupted after initdb leaves a cluster without the database.
    created = subprocess.run(
        [
            pg_bin("createdb"),
            "-h",
            "127.0.0.1",
            "-p",
            str(PORTS["postgres"]),
            "-U",
            "msa",
            PLATFORM_DATABASE,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PGPASSWORD": password},
    )
    if created.returncode and "already exists" not in created.stderr:
        raise SystemExit(created.stderr)


def platform_url(url: str) -> str:
    """The platform database of the stand: an old .env naming the pre-platform database
    "msa" is pointed at "msa_platform", so the old schema and its data stay untouched."""
    base, _, name = url.rpartition("/")
    return f"{base}/{PLATFORM_DATABASE}" if name == "msa" else url


def database(url):
    """Alembic head and the demo catalog; both are idempotent."""
    from demo.pilot import seed_pilot
    from demo.seed_demo import seed_demo
    from msa.db.migrate import migrate
    from msa.db.session import engine

    bind = engine(url)
    try:
        migrate(bind)
        say(f"База: миграции применены, демо-каталог {seed_demo(bind)}")
        seed_pilot(bind)
        say("Стартовый кейс: историческое ипотечное событие, портфель DEMO-1")
    finally:
        bind.dispose()


# Processes --------------------------------------------------------------------------


def busy(name):
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", PORTS[name])) == 0:
            raise SystemExit(f"Порт {PORTS[name]} ({name}) занят другим процессом")


def healthy(name):
    try:
        with urlopen(HEALTH[name], timeout=5) as response:
            return response.status == 200
    except (URLError, OSError):
        return False


def start(name, command, env):
    if healthy(name):
        say(f"{name}: уже работает")
        return None
    busy(name)
    log = open(LOGS / f"{name}.log", "ab")  # noqa: SIM115 - the child owns the handle
    flags = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    process = subprocess.Popen(
        command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, **flags
    )
    (RUN / f"{name}.pid").write_text(str(process.pid))
    return process


def wait(name, process, seconds):
    if process is None:  # Already running and healthy.
        return
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if healthy(name):
            say(f"{name}: готов")
            return
        if process.poll() is not None:
            break
        time.sleep(2)
    tail = (LOGS / f"{name}.log").read_text(errors="replace").splitlines()[-20:]
    raise SystemExit(f"{name}: не поднялся, конец журнала:\n" + "\n".join(tail))


def stop(name):
    pidfile = RUN / f"{name}.pid"
    if not pidfile.exists():
        return
    pid = int(pidfile.read_text())
    # The whole process tree: uvicorn keeps its worker as a child.
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(pid, signal.SIGTERM)  # Started with start_new_session=True.
        except ProcessLookupError:
            pass
    pidfile.unlink()
    say(f"{name}: остановлен")


# Commands ---------------------------------------------------------------------------


def served_models(base_url, key=""):
    request = Request(base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"})
    with urlopen(request, timeout=15) as response:
        return [item["id"] for item in json.load(response)["data"]]


def llm_env(profile):
    """Environment of the API process for one LLM profile, checked before anything starts."""
    if profile == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise SystemExit("Нет DEEPSEEK_API_KEY в переменных окружения пользователя")
        check_llm(DEEPSEEK_URL, key, DEEPSEEK_MODEL)
        say(f"LLM: DeepSeek API, {DEEPSEEK_MODEL} (внешняя: только демо-портфели)")
        # deepseek-flash reasons for 7-8k tokens before a ~4k-token causal answer.
        return {"MSA_LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": key}
    if profile == "local":
        url = os.environ.get("MSA_LLM_BASE_URL", LOCAL_URL)
        try:
            models = served_models(url, os.environ.get("MSA_LLM_API_KEY", ""))
        except (URLError, OSError) as exc:
            raise SystemExit(
                f"Локальная LLM не отвечает на {url}: запустите сервер LM Studio "
                "(Developer → Start Server) и загрузите модель, например gemma-4-12b"
            ) from exc
        model = os.environ.get("MSA_LLM_MODEL") or next(
            (m for m in models if "embed" not in m.lower()), None
        )
        if not model:
            raise SystemExit(f"На {url} не загружена ни одна модель")
        say(f"LLM: локальная, {model} на {url}")
        return {"MSA_LLM_PROVIDER": "local", "MSA_LLM_BASE_URL": url, "MSA_LLM_MODEL": model}
    if profile == "mock":
        say("LLM: заглушка — граф по отраслям портфеля без модели, расчёт настоящий")
        return {"MSA_LLM_PROVIDER": "mock"}
    raise SystemExit("Профиль LLM: deepseek | local | mock")


def up(profile="deepseek"):
    for path in (LOGS, RUN):
        path.mkdir(parents=True, exist_ok=True)
    if init_env(ROOT):
        say("Создан .env с локальными ключами и ролями")
    values = env_file()
    llm = llm_env(profile)
    pg_up(values["POSTGRES_PASSWORD"])
    say(f"PostgreSQL: работает на 127.0.0.1:{PORTS['postgres']}")
    values["MSA_DATABASE_URL"] = platform_url(values["MSA_DATABASE_URL"])
    database(values["MSA_DATABASE_URL"])
    ensure_built(say)
    demo_keys = json.dumps(
        {
            "analyst": values["MSA_UI_ANALYST_API_KEY"],
            "risk_manager": values["MSA_UI_RISK_MANAGER_API_KEY"],
        }
    )
    api = start(
        "api",
        [sys.executable, "-m", "uvicorn", "msa.api.main:app", "--host", "127.0.0.1"]
        + ["--port", str(PORTS["api"]), "--workers", "1"],
        child_env(
            {
                "MSA_DATABASE_URL": values["MSA_DATABASE_URL"],
                "MSA_API_KEYS": values["MSA_API_KEYS"],
                "MSA_CHECKPOINT_MODE": "postgres",
                # The LLM may propose the event's strength as a disclosed demo assumption.
                "MSA_DEMO_ESTIMATE_SCENARIO": "true",
                "MSA_STORAGE_ROOT": str(DATA / "objects"),
                "MSA_UI_DEMO_KEYS": demo_keys,
                **llm,
            }
        ),
    )
    wait("api", api, 90)
    say(
        f"\nСтек поднят: {API}\n"
        "  Войдите как аналитик: «Новый стресс-тест» — текст события, портфель, сила события;\n"
        "  «Портфели» — свой портфель. Каждый прогон: вкладка «Вызовы LLM и MCP».\n"
        f"  API: {API}/docs · Postgres: 127.0.0.1:{PORTS['postgres']}, данные в {PG_DATA}\n"
        "  Журналы: .data/logs · остановка: msa.ps1 down"
    )
    webbrowser.open(f"{API}/new")


def down():
    stop("api")
    if PG_DATA.exists() and pg_running():
        subprocess.run(
            [pg_bin("pg_ctl"), "-D", str(PG_DATA), "-m", "fast", "-w", "stop"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        say(f"postgres: остановлен, данные сохранены в {PG_DATA}")


def status():
    postgres = PG_DATA.exists() and pg_running()
    say(f"postgres   {'работает' if postgres else 'остановлен'}")
    for name in HEALTH:
        say(f"{name:<10} {'работает' if healthy(name) else 'не отвечает'}")


def logs(name=None):
    for path in sorted(LOGS.glob(f"{name or '*'}.log")):
        tail = path.read_text(errors="replace").splitlines()[-40:]
        say(f"==> {path.name}\n" + "\n".join(tail))


def main():
    command, *args = sys.argv[1:] or ["status"]
    commands = {
        "up": up,
        "down": down,
        "status": status,
        "logs": logs,
    }
    if command not in commands:
        raise SystemExit("Команды: up [deepseek|local|mock] | down | status | logs [name]")
    commands[command](*args)


if __name__ == "__main__":
    main()
