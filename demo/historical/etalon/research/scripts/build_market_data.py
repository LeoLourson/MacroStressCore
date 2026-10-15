"""Merge raw MOEX ISS pages into the two JSON deliverables for the Etalon pilot.

Input : $env:TEMP\\etalon-fetch\\etln-page-*.json, bmi-page-*.json (raw ISS responses)
Output: etln-quotes-2023-01_2024-12.json, moex-index-2023-01_2024-12.json

Never overwrites an existing deliverable unless --force is passed.
"""

import glob
import json
import os
import sys
from datetime import date

TMP = os.path.join(os.environ["TEMP"], "etalon-fetch")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RETRIEVED = date.today().isoformat()

ETLN_COLUMNS = ["TRADEDATE", "OPEN", "LOW", "HIGH", "CLOSE", "VOLUME", "VALUE"]
BMI_COLUMNS = ["TRADEDATE", "CLOSE"]


def load_pages(pattern):
    """Concatenate history.data across pages, verifying the column layout."""
    files = sorted(glob.glob(os.path.join(TMP, pattern)))
    if not files:
        raise SystemExit(f"no raw pages match {pattern}")
    rows = []
    columns = None
    for path in files:
        with open(path, encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        page = payload["history"]
        if columns is None:
            columns = page["columns"]
        elif columns != page["columns"]:
            raise SystemExit(f"column layout changed in {path}")
        rows.extend(page["data"])
    return columns, rows


def project(columns, rows, wanted):
    """Keep only `wanted` columns, in that order. Fails loudly on missing columns."""
    index = []
    for name in wanted:
        if name not in columns:
            raise SystemExit(f"column {name} absent from {columns}")
        index.append(columns.index(name))
    return [[row[i] for i in index] for row in rows]


def write_json(path, payload):
    if os.path.exists(path) and "--force" not in sys.argv:
        raise SystemExit(f"refusing to overwrite existing file: {path}")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=4)
        fh.write("\n")
    return len(json.dumps(payload))


def check_dates(rows, date_index):
    dates = [row[date_index] for row in rows]
    assert dates == sorted(dates), "rows are not sorted by date"
    assert len(set(dates)) == len(dates), "duplicate trade dates"
    gaps = [(a, b) for a, b in zip(dates, dates[1:]) if a > b]
    return dates[0], dates[-1], gaps


def main():
    etln_cols, etln_rows = load_pages("etln-page-*.json")
    bmi_cols, bmi_rows = load_pages("bmi-page-*.json")

    etln = project(etln_cols, etln_rows, ETLN_COLUMNS)
    bmi = project(bmi_cols, bmi_rows, BMI_COLUMNS)

    null_close_etln = sum(1 for r in etln if r[4] is None)
    null_close_bmi = sum(1 for r in bmi if r[1] is None)
    print(f"ETLN rows={len(etln)} null CLOSE={null_close_etln}")
    print(f"MOEXBMI rows={len(bmi)} null CLOSE={null_close_bmi}")

    first_e, last_e, _ = check_dates(etln, 0)
    first_b, last_b, _ = check_dates(bmi, 0)
    print(f"ETLN range {first_e} .. {last_e}")
    print(f"MOEXBMI range {first_b} .. {last_b}")

    e_dates = {r[0] for r in etln}
    b_dates = {r[0] for r in bmi}
    only_e = sorted(e_dates - b_dates)
    only_b = sorted(b_dates - e_dates)
    print(f"dates only in ETLN: {only_e}")
    print(f"dates only in index: {only_b}")
    print(f"common trading days: {len(e_dates & b_dates)}")

    quotes = {
        "source": "MOEX ISS",
        "security": "ETLN",
        "board": "TQBR",
        "from": "2023-01-01",
        "till": "2024-12-31",
        "columns": ETLN_COLUMNS,
        "retrieved": RETRIEVED,
        "data": etln,
    }
    index = {
        "source": "MOEX ISS",
        "security": "MOEXBMI",
        "board": "SNDX",
        "name": "Индекс МосБиржи широкого рынка",
        "from": "2023-01-01",
        "till": "2024-12-31",
        "columns": BMI_COLUMNS,
        "retrieved": RETRIEVED,
        "data": bmi,
    }

    q_path = os.path.join(OUT, "etln-quotes-2023-01_2024-12.json")
    i_path = os.path.join(OUT, "moex-index-2023-01_2024-12.json")
    write_json(q_path, quotes)
    write_json(i_path, index)
    print(f"wrote {q_path}")
    print(f"wrote {i_path}")

    lookup = {r[0]: r for r in etln}
    idx_lookup = {r[0]: r for r in bmi}
    print("\nkey dates:")
    for d in ("2023-12-22", "2023-12-29", "2024-06-28", "2024-07-01", "2024-07-31"):
        e, b = lookup.get(d), idx_lookup.get(d)
        print(f"  {d}: ETLN={e}  MOEXBMI={b}")


if __name__ == "__main__":
    main()
