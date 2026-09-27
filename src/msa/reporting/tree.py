"""The metric tree: the one keyed view of a run's numbers.

The report cites it, V9 checks the citations against it, the provenance screen and the MCP
tools read it, the browser resolves the same paths. Each position carries its typed metrics
(``/positions/<id>/metrics/<metric>/p50``) and whatever keyed view its plugin declares for
its details (covenants by id, contributions by channel, derived values); each portfolio
slice carries its statistics and coverage.
"""

from msa.contracts.result import CalculationResult, MetricValue, PortfolioResult


def metric_node(value: MetricValue) -> dict:
    node = {"unit": value.unit}
    if value.value is not None:
        node["value"] = value.value
    if value.quantiles is not None:
        quantiles = value.quantiles
        node.update(p05=quantiles.p05, p50=quantiles.p50, p95=quantiles.p95)
        if quantiles.es95 is not None:
            node["es95"] = quantiles.es95
    return node


def metric_tree(results, portfolio, *, registry, context=None) -> dict:
    """``context`` is what plugins need to project details (the scenario's channel factors)."""
    context = context or {}
    positions = {}
    for result in sorted(
        (CalculationResult.model_validate(r) for r in results), key=lambda r: r.position_id
    ):
        node = {"metrics": {key: metric_node(value) for key, value in result.metrics.items()}}
        plugin = registry.plugins.get(result.plugin_id)
        if plugin is not None and plugin.tree is not None and result.execution == "completed":
            node.update(plugin.tree(result, context))
        positions[result.position_id] = node
    tree = {"positions": positions}
    if portfolio is not None:
        portfolio = PortfolioResult.model_validate(portfolio)
        tree["portfolio"] = {
            "status": portfolio.status,
            "slices": {
                slice_id: {
                    **item.model_dump(mode="json", exclude={"contributions"}),
                    "contributions": {
                        c.position_id: c.model_dump(mode="json") for c in item.contributions
                    },
                    "covered_percent": item.coverage.covered_share * 100,
                    **(
                        {"portfolio_percent": item.coverage.portfolio_share * 100}
                        if item.coverage.portfolio_share is not None
                        else {}
                    ),
                }
                for slice_id, item in portfolio.slices.items()
            },
        }
    return tree
