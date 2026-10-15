"""The demo catalog: portfolios, data snapshots and events, split into synthetic and historical.

The catalog is a set of *collections* of one uniform shape, each with ``events/``,
``portfolios/`` and ``snapshots/``:

- ``demo/synthetic/`` — invented companies, markets and news (``metadata.synthetic`` is true);
- ``demo/historical/<case>/`` — one real historical case per folder (``metadata.synthetic``
  is false), next to its ``sources.json`` and the ``research/`` it was built from.

The core keeps the headers: ``<collection>/portfolios/<portfolio_id>.json`` holds
``{"portfolio": {...}}`` and ``<collection>/snapshots/<snapshot_id>.json`` a snapshot without
its items. Each plugin brings its own part in its own folder, at the same collection path, so a
plugin joins the demo stand without editing a shared file:

- ``src/msa/plugins/<id>/demo_data/<collection>/portfolios/<portfolio_id>.json`` —
  ``{"parties": [...], "instruments": [...], "positions": [...]}``;
- ``src/msa/plugins/<id>/demo_data/<collection>/snapshots/<snapshot_id>.json`` —
  ``{"items": [...]}``.

A plugin part may also carry the header (``"portfolio"``, or the snapshot's fields) of a
portfolio or snapshot the core does not have: a plugin brings a demo portfolio of its own.
Parts are read in the registry's order of plugins, and each list keeps its order within a
part. The same party, instrument, position or item may come from two plugins when it is
identical (a shared issuer); two different records under one identifier are an error, and
so are two headers of one portfolio or snapshot, a part in another collection than its
header, and a header whose ``metadata.synthetic`` contradicts its collection.
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
SYNTHETIC = "synthetic"
HISTORICAL = "historical"


class CatalogError(ValueError):
    """The demo parts of the plugins do not fit together; the message names them."""


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collections(root: Path) -> list[str]:
    """The collections under ``root``: ``synthetic``, then ``historical/<case>`` by name."""
    found = [SYNTHETIC] if (root / SYNTHETIC).is_dir() else []
    if (root / HISTORICAL).is_dir():
        found += [
            f"{HISTORICAL}/{case.name}"
            for case in sorted((root / HISTORICAL).iterdir())
            if case.is_dir() and not case.name.startswith((".", "_"))
        ]
    return found


def is_synthetic(collection: str) -> bool:
    return collection.split("/")[0] == SYNTHETIC


def event_paths(root: Path = CATALOG) -> list[Path]:
    """Every library event of the catalog (``<collection>/events/*.json``), by event id."""
    paths = [path for c in collections(root) for path in (root / c / "events").glob("*.json")]
    return sorted(paths, key=lambda path: path.stem)


def events(root: Path = CATALOG) -> list[dict]:
    """The library events; ``metadata.synthetic`` of each must agree with its collection."""
    found = []
    for path in event_paths(root):
        event = _read(path)
        _check_origin(f"event {path.stem}", path.parent.parent.relative_to(root).as_posix(), event)
        found.append(event)
    return found


def parts(kind: str, registry=None) -> list[tuple[str, str, Path]]:
    """``(plugin_id, collection, file)`` of every plugin's demo part of ``kind``."""
    from importlib.resources import as_file, files

    registry = registry or current()
    found = []
    for plugin_id, plugin in registry.plugins.items():
        try:
            root = files(package_of(plugin)).joinpath(PARTS)
        except ModuleNotFoundError:
            continue  # a plugin declared in code, without a package, has no demo data
        with as_file(root) as folder:
            folder = Path(folder)
            for collection in collections(folder):
                found.extend(
                    (plugin_id, collection, path)
                    for path in sorted((folder / collection / kind).glob("*.json"))
                )
    return found


def _check_origin(what: str, collection: str, header: dict) -> None:
    synthetic = (header.get("metadata") or {}).get("synthetic")
    if synthetic is not None and synthetic is not is_synthetic(collection):
        raise CatalogError(f"{what}: metadata.synthetic={synthetic} in {collection}")


def _headers(kind: str, key: str, registry, root: Path) -> dict[str, tuple[str, str, dict]]:
    """Identifier -> (who declared it, collection, header): the core's, then the plugins'."""
    headers: dict[str, tuple[str, str, dict]] = {}

    def add(where: str, collection: str, path: Path, header: dict) -> None:
        if path.stem in headers:
            raise CatalogError(
                f"{kind[:-1]} {path.stem}: header in {where} and in {headers[path.stem][0]}"
            )
        body = header["portfolio"] if kind == "portfolios" else header
        _check_origin(f"{kind[:-1]} {path.stem}", collection, body)
        headers[path.stem] = (where, collection, header)

    for collection in collections(root):
        for path in sorted((root / collection / kind).glob("*.json")):
            add("demo", collection, path, _read(path))
    for plugin_id, collection, path in parts(kind, registry):
        data = _read(path)
        if key in data:
            add(plugin_id, collection, path, data)
    return headers


def _parts_of(kind: str, identifier: str, collection: str, registry):
    for plugin_id, where, path in parts(kind, registry):
        if path.stem != identifier:
            continue
        if where != collection:
            raise CatalogError(
                f"{kind[:-1]} {identifier}: part of {plugin_id} in {where}, header in {collection}"
            )
        yield plugin_id, _read(path)


def collection_of(kind: str, identifier: str, registry=None, root: Path = CATALOG) -> str:
    """The collection (``synthetic`` or ``historical/<case>``) of a portfolio or snapshot."""
    key = "portfolio" if kind == "portfolios" else "snapshot_id"
    return _headers(kind, key, registry or current(), root)[identifier][1]


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
    _, collection, header = headers[portfolio_id]
    data: dict = {"portfolio": header["portfolio"]}
    data.update({name: [] for name in BUNDLE_LISTS})
    seen: dict[str, dict] = {name: {} for name in BUNDLE_LISTS}
    for plugin_id, part in _parts_of("portfolios", portfolio_id, collection, registry):
        for name, key in BUNDLE_LISTS.items():
            _merge(data[name], part.get(name, []), key, plugin_id, seen[name])
    return data


def snapshot_data(snapshot_id: str, registry=None, root: Path = CATALOG) -> dict:
    """The snapshot: its header and every plugin's items, ordered by item id."""
    registry = registry or current()
    headers = _headers("snapshots", "snapshot_id", registry, root)
    if snapshot_id not in headers:
        raise KeyError(f"no demo snapshot {snapshot_id!r}")
    _, collection, header = headers[snapshot_id]
    data = {key: header[key] for key in SNAPSHOT_HEADER if key in header}
    items: list = []
    seen: dict = {}
    for plugin_id, part in _parts_of("snapshots", snapshot_id, collection, registry):
        _merge(items, part.get("items", []), "item_id", plugin_id, seen)
    data["items"] = sorted(items, key=lambda item: item["item_id"])
    return data


def bundle(portfolio_id: str, registry=None, root: Path = CATALOG) -> PortfolioBundle:
    return PortfolioBundle.model_validate(bundle_data(portfolio_id, registry, root))


def snapshot(snapshot_id: str, registry=None, root: Path = CATALOG) -> DataSnapshot:
    return DataSnapshot.model_validate(snapshot_data(snapshot_id, registry, root))
