"""The demo catalog: portfolios and data snapshots assembled from headers and plugin parts.

The core keeps the headers: ``demo/portfolios/<portfolio_id>.json`` holds ``{"portfolio":
{...}}`` and ``demo/snapshots/<snapshot_id>.json`` a snapshot without its items. Each plugin
brings its own part in its own folder, so a plugin joins the demo stand without editing a
shared file:

- ``src/msa/plugins/<id>/demo_data/portfolios/<portfolio_id>.json`` —
  ``{"parties": [...], "instruments": [...], "positions": [...]}``;
- ``src/msa/plugins/<id>/demo_data/snapshots/<snapshot_id>.json`` — ``{"items": [...]}``.

A plugin part may also carry the header (``"portfolio"``, or the snapshot's fields) of a
portfolio or snapshot the core does not have: a plugin brings a demo portfolio of its own.
Parts are read in the registry's order of plugins, and each list keeps its order within a
part. The same party, instrument, position or item may come from two plugins when it is
identical (a shared issuer); two different records under one identifier are an error, and
so are two headers of one portfolio or snapshot.
"""

import json
from pathlib import Path

from msa.contracts import DataSnapshot, PortfolioBundle
from msa.platform.registry import package_of
from msa.platform.registry import registry as current

CATALOG = Path(__file__).resolve().parent
PARTS = "demo_data"
#: Portfolio lists and the key of their records.
BUNDLE_LISTS = {"parties": "party_id", "instruments": "instrument_id", "positions": "position_id"}
SNAPSHOT_HEADER = ("snapshot_id", "as_of", "label", "kind", "metadata")


class CatalogError(ValueError):
    """The demo parts of the plugins do not fit together; the message names them."""


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parts(kind: str, registry=None) -> list[tuple[str, Path]]:
    """``(plugin_id, file)`` of every plugin's demo part of ``kind`` (portfolios|snapshots)."""
    from importlib.resources import as_file, files

    registry = registry or current()
    found = []
    for plugin_id, plugin in registry.plugins.items():
        try:
            root = files(package_of(plugin)).joinpath(PARTS, kind)
        except ModuleNotFoundError:
            continue  # a plugin declared in code, without a package, has no demo data
        with as_file(root) as folder:
            if Path(folder).is_dir():
                found.extend((plugin_id, path) for path in sorted(Path(folder).glob("*.json")))
    return found


def _headers(kind: str, key: str, registry, root: Path) -> dict[str, tuple[str, dict]]:
    """Identifier -> (who declared it, header): the core's files, then the plugins' parts."""
    headers: dict[str, tuple[str, dict]] = {}
    for path in sorted((root / kind).glob("*.json")):
        header = _read(path)
        headers[path.stem] = ("demo", header)
    for plugin_id, path in parts(kind, registry):
        data = _read(path)
        if key not in data:
            continue
        if path.stem in headers:
            raise CatalogError(
                f"{kind[:-1]} {path.stem}: header in {plugin_id} and in {headers[path.stem][0]}"
            )
        headers[path.stem] = (plugin_id, data)
    return headers


def portfolio_ids(registry=None, root: Path = CATALOG) -> list[str]:
    return sorted(_headers("portfolios", "portfolio", registry or current(), root))


def snapshot_ids(registry=None, root: Path = CATALOG) -> list[str]:
    return sorted(_headers("snapshots", "snapshot_id", registry or current(), root))


def _merge(target: list, records: list, key: str, where: str, seen: dict) -> None:
    for record in records:
        identifier = record[key]
        if identifier in seen:
            owner, first = seen[identifier]
            if first != record:
                raise CatalogError(f"{where}: {key} {identifier} differs from the one in {owner}")
            continue
        seen[identifier] = (where, record)
        target.append(record)


def bundle_data(portfolio_id: str, registry=None, root: Path = CATALOG) -> dict:
    """The portfolio as a bundle: its header and every plugin's parties, instruments, positions."""
    registry = registry or current()
    headers = _headers("portfolios", "portfolio", registry, root)
    if portfolio_id not in headers:
        raise KeyError(f"no demo portfolio {portfolio_id!r}")
    data: dict = {"portfolio": headers[portfolio_id][1]["portfolio"]}
    data.update({name: [] for name in BUNDLE_LISTS})
    seen: dict[str, dict] = {name: {} for name in BUNDLE_LISTS}
    for plugin_id, path in parts("portfolios", registry):
        if path.stem != portfolio_id:
            continue
        part = _read(path)
        for name, key in BUNDLE_LISTS.items():
            _merge(data[name], part.get(name, []), key, plugin_id, seen[name])
    return data


def snapshot_data(snapshot_id: str, registry=None, root: Path = CATALOG) -> dict:
    """The snapshot: its header and every plugin's items, ordered by item id."""
    registry = registry or current()
    headers = _headers("snapshots", "snapshot_id", registry, root)
    if snapshot_id not in headers:
        raise KeyError(f"no demo snapshot {snapshot_id!r}")
    header = headers[snapshot_id][1]
    data = {key: header[key] for key in SNAPSHOT_HEADER if key in header}
    items: list = []
    seen: dict = {}
    for plugin_id, path in parts("snapshots", registry):
        if path.stem == snapshot_id:
            _merge(items, _read(path).get("items", []), "item_id", plugin_id, seen)
    data["items"] = sorted(items, key=lambda item: item["item_id"])
    return data


def bundle(portfolio_id: str, registry=None, root: Path = CATALOG) -> PortfolioBundle:
    return PortfolioBundle.model_validate(bundle_data(portfolio_id, registry, root))


def snapshot(snapshot_id: str, registry=None, root: Path = CATALOG) -> DataSnapshot:
    return DataSnapshot.model_validate(snapshot_data(snapshot_id, registry, root))
