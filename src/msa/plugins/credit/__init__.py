"""Credit plugin: Track A v3.2 for corporate loans, bonds, project finance and leasing.

One ``CreditModel`` per family (``credit.corporate.v3``, ``credit.bond.v3``,
``credit.project_finance.v3``, ``credit.leasing.v3``); the seven drivers are its factors of
the ``graph`` scope; the expected-loss change is its portfolio slice ``credit.loss``.
"""

from msa.plugin_sdk import Plugin, ResultView, SnapshotKindSpec, ViewBlock

from . import calibration
from .demo import cases
from .editor import editor, from_draft
from .factors import FACTORS
from .families import FAMILIES
from .metrics import METRICS, SLICES, instrument_types
from .model import PLUGIN_ID, PLUGIN_VERSION, REGISTRY_OPTION, CreditModel
from .report import ACTIONS, OBSERVATIONS, RULES, SECTIONS, TYPES, tree
from .schemas import FINANCIAL_STATEMENT, RATE
from .wording import AUTHORS, FLAGS, INFORMATIONAL, SOURCES


def run_options(scope: str) -> dict:
    """The calibration registry a namespace calculates with (synthetic only in demo)."""
    return {REGISTRY_OPTION: calibration.for_scope(scope)}


def notes(options: dict) -> dict:
    """Which PD calibration and section-19 inclusion rule the numbers used."""
    return calibration.load(str(options.get(REGISTRY_OPTION) or calibration.NONE)).describe()


plugin = Plugin(
    plugin_id=PLUGIN_ID,
    version=PLUGIN_VERSION,
    sdk=">=1.0,<2.0",
    label="Кредитный риск (Track A v3.2)",
    description="Помесячная модель заёмщика, PD и ожидаемые потери на совместных сценариях.",
    instrument_types=instrument_types(editor, from_draft),
    models=tuple(CreditModel(family) for family in FAMILIES),
    metrics=METRICS,
    factors=FACTORS,
    slices=SLICES,
    snapshot_kinds=(
        SnapshotKindSpec(
            kind=FINANCIAL_STATEMENT,
            label="Финансовая отчётность",
            subject="эмитент (заёмщик) или компания-аналог",
            values={
                item.name: f"{item.label}, {item.unit}"
                for f in FAMILIES
                for item in f.fields_from("statement")
            },
        ),
        SnapshotKindSpec(
            kind=RATE,
            label="Процентная ставка",
            subject="кривая, например risk_free:RUB",
            values={"rate": "ставка, доля"},
        ),
    ),
    views=(
        ResultView(
            view_id="credit.position",
            instrument_types=TYPES,
            component="credit.position",
            labels={
                **{series.name: series.label for f in FAMILIES for series in f.series},
                **{f"covenant:{m.name}": m.label for f in FAMILIES for m in f.covenant_metrics},
                "risk_score": "Индекс риска",
            },
            summary_metrics=(
                "credit.delta_expected_loss",
                "credit.delta_pd",
                "credit.delta_risk_score",
            ),
            blocks=(
                ViewBlock(
                    kind="metrics",
                    title="Итог на конец горизонта",
                    metric_ids=(
                        "credit.delta_expected_loss",
                        "credit.delta_pd",
                        "credit.delta_risk_score",
                        "credit.icr",
                        "credit.funding_gap",
                        "credit.escrow_coverage",
                        "credit.debt_equity",
                        "credit.position_price_change",
                    ),
                ),
                ViewBlock(kind="series", title="Помесячная траектория", path="/stress/series"),
                ViewBlock(
                    kind="table",
                    title="Ковенанты",
                    path="/covenants",
                    columns=(
                        ("covenant_id", "Ковенант"),
                        ("breach_probability", "Вероятность нарушения"),
                        ("min_headroom", "Минимальный запас"),
                    ),
                ),
                ViewBlock(kind="sources", title="Источники данных"),
            ),
        ),
    ),
    report_sections=SECTIONS,
    observations=OBSERVATIONS,
    rules=RULES,
    actions=ACTIONS,
    flags=FLAGS,
    informational_flags=INFORMATIONAL,
    sources=SOURCES,
    authors=AUTHORS,
    tree=tree,
    run_options=run_options,
    notes=notes,
    demo=cases,
)
