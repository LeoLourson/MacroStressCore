"""Рыночные ряды пилота АФК: котировки четырёх акций и индексов МосБиржи с MOEX ISS.

Скачивает страницы истории в ``raw/`` (они и есть доказательство запроса: там колонки
и данные ответа биржи ровно как их отдал ISS) и собирает из них ``market-data.json``.

    uv run --frozen python demo/pilot-afk/fetch_market_data.py
    uv run --frozen python demo/pilot-afk/fetch_market_data.py --check   # сверить с raw/

Окно — с 01.10.2023 по 31.10.2025: год до события нужен для беты, год после — для сверки
оценки с фактом. Существующие страницы в ``raw/`` не перекачиваются и не перезаписываются.
"""

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
OUT = HERE / "market-data.json"
ISS = "https://iss.moex.com/iss"
FROM, TILL = "2023-10-01", "2025-10-31"
PAGE = 100
SHARE_COLUMNS = (
    "TRADEDATE",
    "OPEN",
    "LOW",
    "HIGH",
    "CLOSE",
    "LEGALCLOSEPRICE",
    "VOLUME",
    "VALUE",
    "SECID",
    "BOARDID",
)
INDEX_COLUMNS = ("TRADEDATE", "OPEN", "LOW", "HIGH", "CLOSE", "VOLUME", "VALUE", "SECID", "BOARDID")
#: Ключ -> (колонки, путь истории ISS).
SECURITIES = {
    "MTSS": (SHARE_COLUMNS, "history/engines/stock/markets/shares/boards/TQBR/securities/MTSS"),
    "OZON": (SHARE_COLUMNS, "history/engines/stock/markets/shares/boards/TQBR/securities/OZON"),
    "SGZH": (SHARE_COLUMNS, "history/engines/stock/markets/shares/boards/TQBR/securities/SGZH"),
    "ETLN": (SHARE_COLUMNS, "history/engines/stock/markets/shares/boards/TQBR/securities/ETLN"),
    "MOEXBMI": (INDEX_COLUMNS, "history/engines/stock/markets/index/securities/MOEXBMI"),
    # Отраслевые индексы МосБиржи: по ним видно, как вели себя отрасли портфеля
    # сверх широкого рынка.
    "MOEXRE": (INDEX_COLUMNS, "history/engines/stock/markets/index/securities/MOEXRE"),
    "MOEXMM": (INDEX_COLUMNS, "history/engines/stock/markets/index/securities/MOEXMM"),
    "MOEXTL": (INDEX_COLUMNS, "history/engines/stock/markets/index/securities/MOEXTL"),
    "MOEXCN": (INDEX_COLUMNS, "history/engines/stock/markets/index/securities/MOEXCN"),
}


def pages(ticker: str, path: str, client: httpx.Client) -> list[dict]:
    """Все страницы истории бумаги; пустая страница заканчивает перебор."""
    found, start = [], 0
    while True:
        response = client.get(
            f"{ISS}/{path}.json",
            params={"from": FROM, "till": TILL, "start": start, "iss.only": "history"},
        )
        response.raise_for_status()
        history = response.json()["history"]
        if start == 0:
            found.append({"columns": history["columns"], "data": history["data"]})
        elif history["data"]:
            found.append({"columns": history["columns"], "data": history["data"]})
        if len(history["data"]) < PAGE:
            return found
        start += PAGE
        time.sleep(0.3)  # вежливость к бирже


def download() -> list[Path]:
    RAW.mkdir(parents=True, exist_ok=True)
    written = []
    with httpx.Client(timeout=60, headers={"User-Agent": "MacroStressCore pilot-afk"}) as client:
        for ticker, (_, path) in SECURITIES.items():
            found = pages(ticker, path, client)
            for number, page in enumerate(found):
                target = RAW / f"{ticker}-page-{number:03d}.json"
                if target.exists():
                    continue
                target.write_text(
                    json.dumps(page, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
                )
                written.append(target)
            print(f"{ticker}: страниц {len(found)}", flush=True)
    return written


def project(columns: list[str], rows: list[list], wanted: tuple[str, ...]) -> list[list]:
    missing = [name for name in wanted if name not in columns]
    if missing:
        raise SystemExit(f"в ответе биржи нет колонок {missing}: {columns}")
    index = [columns.index(name) for name in wanted]
    return [[row[i] for i in index] for row in rows]


def merge(ticker: str) -> dict:
    columns, _ = SECURITIES[ticker]
    files = sorted(RAW.glob(f"{ticker}-page-*.json"))
    if not files:
        raise SystemExit(f"нет страниц {ticker} в {RAW}: сначала запусти без --check")
    layout, rows = None, []
    for path in files:
        page = json.loads(path.read_text(encoding="utf-8"))
        if layout is None:
            layout = page["columns"]
        elif layout != page["columns"]:
            raise SystemExit(f"раскладка колонок изменилась в {path}")
        rows.extend(page["data"])
    data = project(layout, rows, columns)
    dates = [row[0] for row in data]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise SystemExit(f"{ticker}: даты не отсортированы или повторяются")
    return {
        "security": ticker,
        "columns": list(columns),
        "rows": len(data),
        "from": dates[0],
        "till": dates[-1],
        "data": data,
    }


def build() -> str:
    payload = {
        "source": "MOEX ISS",
        "url": f"{ISS}/history",
        "retrieved": date.today().isoformat(),
        "note": "Котировки режима TQBR, индекс МосБиржи широкого рынка (MOEXBMI, SNDX) и "
        "отраслевые индексы МосБиржи: недвижимость (MOEXRE), металлы и добыча (MOEXMM), "
        "телекоммуникации (MOEXTL), потребительский сектор (MOEXCN); "
        "сырые ответы биржи — в raw/",
        "securities": {ticker: merge(ticker) for ticker in SECURITIES},
    }
    return json.dumps(payload, ensure_ascii=False, indent=1) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="не качать, только сверить с raw/")
    args = parser.parse_args()
    if not args.check:
        for path in download():
            print(f"скачано {path.relative_to(HERE.parent.parent)}")
    text = build()
    current = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    if current == text:
        print(f"{OUT.relative_to(HERE.parent.parent)}: без изменений")
        return 0
    if args.check:
        print(f"{OUT.relative_to(HERE.parent.parent)}: расходится с raw/")
        return 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"записано {OUT.relative_to(HERE.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
