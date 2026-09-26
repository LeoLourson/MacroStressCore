"""The Track A profile of a credit position, assembled from the platform's data.

The borrower's figures come from its financial statement in the data snapshot, the latest
one dated no later than the valuation date (audit finding A2: a historical stress never
reads a later statement). The instrument's contractual terms and the snapshot's market
quotes complete the family's inputs. The data-quality score and the peer substitution are
those of the exposure agent before the platform (TZ 3.3), now a pure function of the
prepared inputs.
"""

from math import exp

from msa.contracts.evidence import Parameter
from msa.plugin_sdk import DataRequirement, DataRequirements, FactorRequirement

from .contracts import CreditProfile
from .factors import FACTORS
from .families import family_for
from .schemas import FINANCIAL_STATEMENT, CreditPosition, terms_for

STATEMENT = "statement"
PEERS = "peers"
MARKET_PREFIX = "market:"
_SOURCE_WEIGHTS = {"IFRS": 1.0, "RAS": 0.8, "management": 0.5, "proxy": 0.2}
STANDARDS = ["IFRS", "RAS"]


def data_quality(completeness, age_days, standard, *, limited_disclosure=False):
    if not 0 <= completeness <= 1 or age_days < 0 or standard not in _SOURCE_WEIGHTS:
        raise ValueError("Invalid data quality inputs")
    dq = 0.4 * completeness + 0.3 * exp(-age_days / 365) + 0.3 * _SOURCE_WEIGHTS[standard]
    return min(dq, 0.5) if limited_disclosure else min(dq, 1.0)


def requirements(context) -> DataRequirements:
    family = family_for(context.instrument.instrument_type)
    issuer = context.instrument.issuer_id
    params = CreditPosition.model_validate(context.position.params)
    data = [
        DataRequirement(
            key=STATEMENT,
            kind=FINANCIAL_STATEMENT,
            subject=issuer,
            required=False,
            prefer_attribute="standard",
            prefer_order=STANDARDS,
            purpose="отчётность заёмщика на дату оценки",
        ),
        DataRequirement(
            key=PEERS,
            kind=FINANCIAL_STATEMENT,
            required=False,
            many=True,
            prefer_attribute="standard",
            prefer_order=STANDARDS,
            purpose="компании-аналоги при недостатке данных",
            **(
                {"subjects": params.proxy_peer_ids}
                if params.proxy_peer_ids
                else {"peers_of": issuer}
            ),
        ),
    ]
    for item in family.fields_from("market"):
        kind, subject, _ = item.market
        data.append(
            DataRequirement(
                key=MARKET_PREFIX + item.name,
                kind=kind,
                subject=subject.format(currency=context.instrument.currency),
                required=False,
                purpose=item.label,
            )
        )
    return DataRequirements(
        data=data, factors=[FactorRequirement(factor_id=spec.factor_id) for spec in FACTORS]
    )


def financials(prepared) -> dict[str, Parameter]:
    """The family's inputs: statement figures, contractual terms and market quotes."""
    context = prepared.context
    family = family_for(context.instrument.instrument_type)
    values: dict[str, Parameter] = {}
    statement = prepared.item(STATEMENT)
    if statement is not None:
        declared = {item.name for item in family.fields_from("statement")}
        values.update({k: v for k, v in statement.values.items() if k in declared})
    terms = terms_for(family).model_validate(context.instrument.terms)
    for item in family.fields_from("terms"):
        parameter = getattr(terms, item.name)
        if parameter is not None:
            values[item.name] = parameter
    for item in family.fields_from("market"):
        quote = prepared.item(MARKET_PREFIX + item.name)
        if quote is not None and item.market[2] in quote.values:
            values[item.name] = quote.values[item.market[2]]
    return dict(sorted(values.items()))


def build(prepared) -> CreditProfile:
    """The profile Track A reads, with its data-quality score and peer substitution."""
    context = prepared.context
    family = family_for(context.instrument.instrument_type)
    params = CreditPosition.model_validate(context.position.params)
    terms = terms_for(family).model_validate(context.instrument.terms)
    statement = prepared.item(STATEMENT)
    peers = prepared.items(PEERS)
    own = financials(prepared)
    flags = sorted(set(params.flags))
    status = params.status

    standard = (statement.attributes.get("standard") if statement else None) or (
        "proxy" if not own else "management"
    )
    if standard == "IFRS" and not (statement and statement.attributes.get("audited", False)):
        standard = "management"
    if "proxy_required" in flags:
        standard = "proxy"
    if standard not in _SOURCE_WEIGHTS:
        standard = "management"
    period = statement.observed_on if statement is not None else prepared.as_of
    age = max(0, (prepared.as_of - period).days)
    disclosure = set(family.disclosure)
    completeness = len(disclosure.intersection(own)) / len(disclosure)
    dq = data_quality(completeness, age, standard, limited_disclosure="limited_disclosure" in flags)
    field_evidence = {
        "ead": list(params.ead.evidence),
        "lgd": list(params.lgd.evidence),
        "ccf": list(params.ccf.evidence),
        "import_share": list(params.import_share.evidence),
        "dq": list(own[min(own)].evidence) if own else list(params.ead.evidence),
    }
    values = dict(own)
    proxy_ids = set(params.proxy_peer_ids)
    if dq < 0.4:
        by_name: dict[str, list[Parameter]] = {}
        for peer in peers:
            for name, parameter in peer.values.items():
                by_name.setdefault(name, []).append(parameter)
        for name in sorted(family.required - set(values)):
            available = by_name.get(name, [])
            if available:
                values[name] = Parameter(
                    value=sum(p.value for p in available) / len(available),
                    unit=available[0].unit,
                    evidence=[e for p in available for e in p.evidence],
                )
        proxy_ids |= {peer.subject for peer in peers}
        if proxy_ids:
            flags = sorted(set(flags) | {"proxy_required"})
    if not values and not proxy_ids:
        status = "needs_review"
        flags = sorted(set(flags) | {"missing_financials_and_peers"})
    elif not family.required.issubset(values):
        status = "needs_review"
        flags = sorted(set(flags) | {"incomplete_model_inputs"})
    return CreditProfile(
        asset_id=context.position.position_id,
        okved=context.issuer.okved,
        asset_type=context.instrument.instrument_type,
        ead=params.ead.value,
        lgd=params.lgd.value,
        financials=dict(sorted(values.items())),
        dq=dq,
        covenants=terms.covenants,
        proxy_peer_ids=sorted(proxy_ids),
        collateral=terms.collateral,
        ccf=params.ccf.value,
        import_share=params.import_share.value,
        field_evidence=field_evidence,
        driver_elasticity=params.driver_elasticity,
        status=status,
        flags=flags,
    )
