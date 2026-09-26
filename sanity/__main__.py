"""Run the common-sense checks: ``uv run python -m sanity [CHECK_ID ...] [--json PATH]
[--markdown PATH]``.

Prints one line per check and a summary; ``--json`` also writes every verdict with its
numbers, ``--markdown`` a table of them. The exit code is 0 whatever the verdicts: this is
an evaluation, not a gate.
"""

import argparse
import json
import sys
import time
import traceback

from .checks import CHECKS, GROUPS
from .lab import Verdict

MARKS = {True: "OK  ", False: "FAIL", None: "N/A "}
WORDS = {True: "соответствует", False: "**не соответствует**", None: "не проверено"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sanity")
    parser.add_argument("ids", nargs="*", help="check ids (A1, B6, ...) or groups (A, B, ...)")
    parser.add_argument("--json", help="write the verdicts to this file")
    parser.add_argument("--markdown", help="write a table of the verdicts to this file")
    args = parser.parse_args(argv)
    chosen = [c for c in CHECKS if not args.ids or c.check_id in args.ids or c.group in args.ids]
    records, started = [], time.time()
    group = None
    for item in chosen:
        if item.group != group:
            group = item.group
            print(f"\n{group}. {GROUPS[group]}")
        began = time.time()
        try:
            verdict = item.fn()
        except Exception as exc:  # noqa: BLE001 - a crash is a verdict of its own
            verdict = Verdict(None, f"исключение {type(exc).__name__}: {exc}")
            traceback.print_exc(file=sys.stderr)
        seconds = time.time() - began
        known = f" [известно: {item.known}]" if item.known else ""
        print(f"  {MARKS[verdict.ok]} {item.check_id:<4} {item.title}{known}")
        print(f"       {verdict.observed}")
        records.append(
            {
                "check_id": item.check_id,
                "group": item.group,
                "title": item.title,
                "expectation": item.expectation,
                "portfolio": item.portfolio,
                "event": item.event,
                "known": item.known,
                "ok": verdict.ok,
                "observed": verdict.observed,
                "numbers": verdict.numbers,
                "seconds": round(seconds, 2),
            }
        )
    passed = sum(r["ok"] is True for r in records)
    failed = sum(r["ok"] is False for r in records)
    unknown = sum(r["ok"] is None for r in records)
    print(
        f"\nИтого {len(records)}: соответствуют здравому смыслу {passed}, "
        f"не соответствуют {failed}, не проверено {unknown}; {time.time() - started:.0f} с"
    )
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=1, default=str)
            handle.write("\n")
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as handle:
            handle.write(markdown(records, passed, failed, unknown))
    return 0


def markdown(records, passed, failed, unknown) -> str:
    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Проверки здравого смысла: результаты прогона",
        "",
        "Файл создан командой `uv run python -m sanity --markdown sanity/results.md`; разбор — в",
        "[docs/sanity-report.md](../docs/sanity-report.md).",
        "",
        f"Всего {len(records)}: соответствуют здравому смыслу {passed}, не соответствуют "
        f"{failed}, не проверено {unknown}.",
    ]
    group = None
    for r in records:
        if r["group"] != group:
            group = r["group"]
            lines += [
                "",
                f"## {group}. {GROUPS[group]}",
                "",
                "| ID | Проверка | Портфель | Событие | Ожидание | Результат | Вердикт |",
                "|---|---|---|---|---|---|---|",
            ]
        verdict = WORDS[r["ok"]] + (f" (известно: {r['known']})" if r["known"] else "")
        lines.append(
            "| "
            + " | ".join(
                cell(v)
                for v in (
                    r["check_id"],
                    r["title"],
                    r["portfolio"],
                    r["event"],
                    r["expectation"],
                    r["observed"],
                    verdict,
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
