"""The core/plugin boundary: core code (``msa`` outside ``msa.plugins.<id>``, the web UI
outside ``ui/web/src/plugins/<id>``) must never name a plugin, one of its instrument types
or one of its snapshot kinds as a string literal. A finding here means core code names a
plugin: move that code into the plugin, or add an extension point to the SDK.
"""

import ast
import tomllib
from pathlib import Path

from msa.platform.registry import registry

REPO_ROOT = Path(__file__).resolve().parents[2]
PY_ROOT = REPO_ROOT / "src" / "msa"
TS_ROOT = REPO_ROOT / "ui" / "web" / "src"

#: (repo-relative path, literal) -> why this one hit is not a boundary violation. An entry
#: that stops matching anything must itself fail the test below, so it cannot rot.
ALLOW_LIST = {
    ("src/msa/contracts/snapshot.py", "market"): (
        "the origin of a snapshot (imported market feeds), not the market plugin"
    ),
}


# -- identifiers, from the live registry -----------------------------------------------


def plugin_identifiers() -> tuple[set[str], set[str]]:
    """(exact identifiers, dotted prefixes) for every plugin but the built-in ``core``."""
    exact: set[str] = set()
    prefixes: set[str] = set()
    for plugin_id, plugin in registry().plugins.items():
        if plugin_id == "core":
            continue
        exact.add(plugin_id)
        prefixes.add(f"{plugin_id}.")
        exact.update(spec.type_id for spec in plugin.instrument_types)
        exact.update(spec.kind for spec in plugin.snapshot_kinds)
    return exact, prefixes


def _violates(literal: str, exact: set[str], prefixes: set[str]) -> bool:
    return literal in exact or any(literal.startswith(prefix) for prefix in prefixes)


# -- which files are core -----------------------------------------------------------------


def _is_inside_a_plugin(path: Path, plugins_dir: Path) -> bool:
    """True for a file under ``plugins_dir/<id>/...``; false for one directly in it."""
    try:
        rel = path.relative_to(plugins_dir)
    except ValueError:
        return False
    return len(rel.parts) > 1


def iter_python_core_files(root: Path) -> list[Path]:
    plugins_dir = root / "plugins"
    return sorted(p for p in root.rglob("*.py") if not _is_inside_a_plugin(p, plugins_dir))


def iter_ts_core_files(root: Path) -> list[Path]:
    plugins_dir = root / "plugins"
    paths = [p for p in root.rglob("*.ts") if not _is_inside_a_plugin(p, plugins_dir)]
    paths += [p for p in root.rglob("*.tsx") if not _is_inside_a_plugin(p, plugins_dir)]
    return sorted(paths)


# -- Python string literals, docstrings excluded ----------------------------------------


def python_string_literals(path: Path) -> list[tuple[int, str]]:
    """Every ``ast.Constant`` string in the file, including f-string chunks, minus docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


# -- TS/TSX string literals: a small pure-Python scanner --------------------------------

#: A previous significant character after which ``/`` opens a regex literal.
_TRIGGER_CHARS = set("(,=:[!&|?{};+-*%<>~^")
#: A previous *token* after which ``/`` opens a regex literal, even though it is a word.
_KEYWORDS_BEFORE_REGEX = {"return", "typeof", "case", "in", "of"}
_WORD_START = set("_$")


def _is_word_char(ch: str | None) -> bool:
    return ch is not None and (ch.isalnum() or ch in _WORD_START)


def _consume_regex(text: str, i: int) -> int:
    """``text[i]`` is the opening ``/`` of a regex literal; returns the index past its flags."""
    n = len(text)
    j = i + 1
    in_class = False
    while j < n:
        ch = text[j]
        if ch == "\\" and j + 1 < n:
            j += 2
            continue
        if ch == "\n":
            return j  # a regex cannot span a line; give up where we are
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            j += 1
            while j < n and text[j].isalpha():
                j += 1
            return j
        j += 1
    return j


def _consume_quoted(text: str, i: int) -> tuple[int, str | None]:
    """``text[i]`` is ``'`` or ``\"``. A quote never spans a newline: past one, drop it."""
    quote = text[i]
    n = len(text)
    j = i + 1
    while j < n:
        ch = text[j]
        if ch == "\\" and j + 1 < n:
            j += 2
            continue
        if ch == quote:
            return j + 1, text[i + 1 : j]
        if ch == "\n":
            return j, None  # caller resumes scanning right at the newline
        j += 1
    return j, None


def _scan(text: str, i: int, line: int, literals: list, stop_at_rbrace: bool) -> tuple[int, int]:
    """Scan TS/TSX code from ``i``; append ``(line, value)`` literals found along the way.

    ``stop_at_rbrace`` scans one ``${...}`` template expression: it returns right after the
    ``}`` that closes it, at brace depth zero; a plain code region ignores unmatched ``}``.
    """
    n = len(text)
    last_significant: str | None = None
    last_word = ""
    depth = 0
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            end = n if j == -1 else j + 2
            line += text.count("\n", i, end)
            i = end
            continue
        if c == "`":
            i, line = _consume_template(text, i, line, literals)
            last_significant, last_word = "`", ""
            continue
        if c in "'\"":
            start_line = line
            new_i, value = _consume_quoted(text, i)
            if value is not None:
                literals.append((start_line, value))
                last_significant, last_word = c, ""
            i = new_i
            continue
        if c == "/":
            # JSX: ``</Tag>`` closes an element and ``/>`` a self-closing one, not a regex.
            jsx = last_significant == "<" or (i + 1 < n and text[i + 1] == ">")
            is_regex = not jsx and (last_significant is None or last_significant in _TRIGGER_CHARS)
            is_regex = is_regex or (
                _is_word_char(last_significant) and last_word in _KEYWORDS_BEFORE_REGEX
            )
            if is_regex:
                i = _consume_regex(text, i)
                last_significant, last_word = ")", ""
            else:
                i += 1
                last_significant, last_word = "/", ""
            continue
        if c == "{":
            depth += 1
            i += 1
            last_significant, last_word = "{", ""
            continue
        if c == "}":
            if stop_at_rbrace and depth == 0:
                return i + 1, line
            depth -= 1
            i += 1
            last_significant, last_word = "}", ""
            continue
        if c.isalnum() or c in _WORD_START:
            j = i
            while j < n and (text[j].isalnum() or text[j] in _WORD_START):
                j += 1
            last_word = text[i:j]
            last_significant = text[j - 1]
            i = j
            continue
        last_significant, last_word = c, ""
        i += 1
    return i, line


def _consume_template(text: str, i: int, line: int, literals: list) -> tuple[int, int]:
    """``text[i]`` is the opening backtick; yields each static chunk as a literal."""
    n = len(text)
    j = i + 1
    chunk_start, chunk_line = j, line
    while j < n:
        ch = text[j]
        if ch == "\\" and j + 1 < n:
            j += 2
            continue
        if ch == "`":
            literals.append((chunk_line, text[chunk_start:j]))
            return j + 1, line
        if ch == "\n":
            line += 1
            j += 1
            continue
        if ch == "$" and j + 1 < n and text[j + 1] == "{":
            literals.append((chunk_line, text[chunk_start:j]))
            j, line = _scan(text, j + 2, line, literals, stop_at_rbrace=True)
            chunk_start, chunk_line = j, line
            continue
        j += 1
    literals.append((chunk_line, text[chunk_start:j]))
    return j, line


def ts_string_literals(text: str) -> list[tuple[int, str]]:
    """Every string, template-literal chunk and JSX attribute string; no regex, no comments."""
    literals: list[tuple[int, str]] = []
    _scan(text, 0, 1, literals, stop_at_rbrace=False)
    return literals


# -- putting a root and a set of identifiers together -----------------------------------


def find_python_violations(
    root: Path, exact: set[str], prefixes: set[str]
) -> list[tuple[Path, int, str]]:
    return [
        (path, line, literal)
        for path in iter_python_core_files(root)
        for line, literal in python_string_literals(path)
        if _violates(literal, exact, prefixes)
    ]


def find_ts_violations(
    root: Path, exact: set[str], prefixes: set[str]
) -> list[tuple[Path, int, str]]:
    return [
        (path, line, literal)
        for path in iter_ts_core_files(root)
        for line, literal in ts_string_literals(path.read_text(encoding="utf-8"))
        if _violates(literal, exact, prefixes)
    ]


def _real_findings() -> list[tuple[str, int, str]]:
    """(repo-relative path, line, literal) for every boundary hit in the real tree."""
    exact, prefixes = plugin_identifiers()
    raw = [
        *find_python_violations(PY_ROOT, exact, prefixes),
        *find_ts_violations(TS_ROOT, exact, prefixes),
    ]
    return [(str(path.relative_to(REPO_ROOT)), line, literal) for path, line, literal in raw]


# -- the main test ------------------------------------------------------------------------


def test_core_does_not_name_a_plugin():
    findings = [f for f in _real_findings() if (f[0], f[2]) not in ALLOW_LIST]
    listing = "\n".join(f"{path}:{line}: {literal!r}" for path, line, literal in findings)
    assert findings == [], (
        "core code names a plugin; move the code into that plugin, or add an extension "
        f"point to the SDK:\n{listing}"
    )


def test_allow_list_entries_still_match_something():
    present = {(path, literal) for path, _, literal in _real_findings()}
    stale = sorted(key for key in ALLOW_LIST if key not in present)
    assert stale == [], f"allow-list entries no longer match anything, remove them: {stale}"


# -- the TS/TSX scanner, on inline samples ------------------------------------------------


def test_ts_scanner_ignores_quotes_inside_comments():
    text = "// it's a \"comment\" full of quotes\nconst a = 'real';\n"
    assert ts_string_literals(text) == [(2, "real")]


def test_ts_scanner_splits_a_template_literal_around_its_expressions():
    text = "`a ${x ? 'credit.icr' : \"b\"} c`"
    assert [value for _, value in ts_string_literals(text)] == ["a ", "credit.icr", "b", " c"]


def test_ts_scanner_regex_literal_is_not_mistaken_for_a_string():
    assert ts_string_literals("const r = /[a-z]'x/g;\n") == []


def test_ts_scanner_division_is_not_mistaken_for_a_regex():
    assert ts_string_literals("const q = a / b / c;\n") == []


def test_ts_scanner_jsx_apostrophe_does_not_swallow_the_following_lines():
    text = "<Term name=\"PD\">Don't</Term>\nconst y = 'next';\n"
    assert ts_string_literals(text) == [(1, "PD"), (2, "next")]


def test_ts_scanner_jsx_closing_tags_are_not_regex_literals():
    text = "<b>x</b>{' '}<Foo {...p} /><Term name=\"PD\">y</Term>\n"
    assert [value for _, value in ts_string_literals(text)] == [" ", "PD"]


# -- end to end, on a synthetic core -------------------------------------------------------


def test_boundary_scan_ignores_docstrings_and_comments(tmp_path):
    (tmp_path / "core.py").write_text(
        '"""A module docstring that mentions credit.icr; it must not count."""\n\n'
        'X = "credit.icr"\n',
        encoding="utf-8",
    )
    (tmp_path / "core.tsx").write_text(
        "// a comment mentioning 'equity'; it must not count\nconst a = 'common_stock';\n",
        encoding="utf-8",
    )
    exact, prefixes = {"common_stock", "equity"}, {"credit."}
    findings = [
        *find_python_violations(tmp_path, exact, prefixes),
        *find_ts_violations(tmp_path, exact, prefixes),
    ]
    assert sorted(literal for _, _, literal in findings) == ["common_stock", "credit.icr"]


# -- the import-linter contract for plugins is not loosened -------------------------------


def test_import_linter_still_forbids_every_other_msa_subpackage_to_plugins():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    name = "Plugins import only msa.plugin_sdk, msa.contracts and their own package"
    contract = next(c for c in contracts if c["name"] == name)

    assert contract["forbidden_modules"] == ["msa.*"]
    ignored = set(contract["ignore_imports"])
    assert ignored == {
        "msa.plugins.** -> msa.plugin_sdk",
        "msa.plugins.** -> msa.plugin_sdk.**",
        "msa.plugins.** -> msa.contracts",
        "msa.plugins.** -> msa.contracts.**",
        "msa.plugins.*.tests.** -> msa.**",
    }

    # And the wildcard actually has other subpackages left to forbid: the config guards
    # something real, not a package list that happens to be empty.
    top_level = {
        entry.stem
        for entry in PY_ROOT.iterdir()
        if not entry.name.startswith("__") and (entry.is_dir() or entry.suffix == ".py")
    }
    other_subpackages = top_level - {"plugins", "plugin_sdk", "contracts"}
    assert other_subpackages
    for name in other_subpackages:
        assert f"msa.{name}" not in ignored
        assert f"msa.{name}.**" not in ignored
