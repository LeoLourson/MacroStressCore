"""The causal agent's vocabulary, derived from the selected models of this portfolio.

No asset family is special here. Plugins supply factor semantics and per-position keys
through FactorSpec and CalculationModel.requirements; private valuation inputs stay out
of the prompt.
"""

from dataclasses import asdict

from msa.contracts.domain import PositionContext


def portfolio_context(positions, options, registry) -> dict:
    factors, models, assets = {}, {}, []
    for raw in positions:
        position = PositionContext.model_validate(raw)
        asset = {
            "position_id": position.position_id,
            "instrument_type": position.instrument.instrument_type,
            "okved": position.okved,
        }
        try:
            model = registry.model_for(position)
        except KeyError:
            assets.append({**asset, "unsupported": True, "factors": []})
            continue
        needs = model.requirements(position, options)
        refs = []
        for item in needs.factors:
            if item.factor_id not in model.factors or item.factor_id not in registry.factors:
                raise ValueError(f"{model.model_id}: undeclared required factor {item.factor_id}")
            spec = registry.factors[item.factor_id]
            factors[spec.factor_id] = asdict(spec)
            refs.append(item.model_dump(mode="json"))
        models[model.model_id] = {
            "model_id": model.model_id,
            "label": model.label,
            "description": model.description,
            "instrument_types": list(model.instrument_types),
        }
        assets.append({**asset, "model_id": model.model_id, "factors": refs})
    return {
        "horizon_months": options.horizon,
        "base_currency": options.base_currency,
        "models": [models[key] for key in sorted(models)],
        "factors": [factors[key] for key in sorted(factors)],
        "positions": sorted(assets, key=lambda item: item["position_id"]),
    }
