from datetime import date

from pydantic import ValidationError

from msa.contracts.common import Contract, Identifier
from msa.contracts.evidence import Evidence, Parameter
from msa.contracts.graph import TransmissionGraph
from msa.contracts.scenario import MacroParameter, central_value


class ScenarioParameter(MacroParameter):
    """A draw parameter with the words it was translated from; the analyst confirms it."""

    label: Identifier
    evidence: list[Evidence] = []

    def macro(self) -> MacroParameter:
        return MacroParameter.model_validate(self.model_dump(exclude={"label", "evidence"}))


class EventPassport(Contract):
    event_type: Identifier
    authority: Identifier | None = None
    act_reference: Identifier | None = None
    effective_date: date | None = None
    territory: Identifier | None = None


class CausalOutput(Contract):
    passport: EventPassport
    parameters: dict[Identifier, Parameter]
    direct_okved: list[Identifier]
    inferred_okved: list[Identifier]
    graph: TransmissionGraph
    scenario: dict[Identifier, ScenarioParameter] = {}
    prompt_version: Identifier = "v5"

    @property
    def all_okved(self):
        return set(self.direct_okved) | set(self.inferred_okved)


# Parameters without a factor replace a model input instead of shocking a factor.
STRUCTURAL_PARAMETERS = {"elasticity"}


def _factors():
    from msa.platform.registry import registry

    return registry().factors


def scenario_violations(scenario, graph, *, required=False) -> list[dict]:
    """Why a scenario cannot be calculated on this graph, as failed verdicts."""

    def problem(path, message):
        return {"rule_id": "SCENARIO", "ok": False, "path": path, "message": message}

    factors = _factors()
    problems, parameters = [], {}
    for name, spec in (scenario or {}).items():
        try:
            parameters[name] = ScenarioParameter.model_validate(spec)
        except ValidationError as exc:
            message = f"Параметр задан неполно: {exc.errors()[0]['msg']}"
            problems.append(problem(f"/macro_parameters/{name}", message))
    try:
        graph = TransmissionGraph.model_validate(graph)
    except ValueError:
        graph = None
    nodes = {node.id: node for node in graph.nodes} if graph else {}
    for name, parameter in parameters.items():
        path = f"/macro_parameters/{name}"
        if parameter.factor is None:
            if (
                name not in STRUCTURAL_PARAMETERS
                or parameter.unit != "dimensionless"
                or parameter.channel is not None
            ):
                problems.append(
                    problem(path, "Без фактора можно задать только эластичность спроса.")
                )
            continue
        spec = factors.get(parameter.factor)
        if spec is None:
            problems.append(problem(path, f"Неизвестный фактор «{parameter.factor}»."))
            continue
        if parameter.unit != spec.unit:
            problems.append(
                problem(path, f"Для фактора «{spec.label}» нужна единица «{spec.unit}».")
            )
        lowest = parameter.value if parameter.kind == "point" else parameter.low
        if spec.lower_bound is not None and lowest is not None and lowest <= spec.lower_bound:
            problems.append(
                problem(
                    path,
                    f"Шок фактора «{spec.label}» выходит из его области: значение должно быть "
                    f"больше {spec.lower_bound:g}.",
                )
            )
        if spec.scope != "graph":
            if parameter.key is None:
                label = spec.key_label or "ключ фактора"
                problems.append(problem(path, f"Для фактора «{spec.label}» укажите {label}."))
            if (
                parameter.channel is not None
                and graph is not None
                and (parameter.channel not in nodes or nodes[parameter.channel].kind != "channel")
            ):
                problems.append(problem(path, f"В графе нет канала «{parameter.channel}»."))
            continue
        if parameter.channel is None:
            problems.append(problem(path, "Не указан канал графа, через который действует шок."))
            continue
        if parameter.key is not None:
            problems.append(problem(path, "Фактор графа не имеет ключа: он доходит через отрасли."))
        if graph is None:
            continue
        if parameter.channel not in nodes or nodes[parameter.channel].kind != "channel":
            problems.append(problem(path, f"В графе нет канала «{parameter.channel}»."))
        elif not any(
            graph.simple_paths(parameter.channel, node.id)
            for node in graph.nodes
            if node.kind == "factor" and node.factor == parameter.factor
        ):
            problems.append(
                problem(
                    path,
                    f"Канал «{parameter.channel}» не доходит в графе до фактора «{spec.label}».",
                )
            )
    if required and not any(p.factor for p in parameters.values()):
        problems.append(
            problem(
                "/macro_parameters",
                "Сценарий не задан: добавьте хотя бы один параметр, двигающий фактор.",
            )
        )
    return problems


def reachable_factors(graph, channel) -> list[str]:
    """Graph factors the channel reaches, in the registry's order."""
    try:
        parsed = TransmissionGraph.model_validate(graph)
    except ValueError:
        return []
    if channel not in {node.id for node in parsed.nodes}:
        return []
    kinds = {
        node.factor
        for node in parsed.nodes
        if node.kind == "factor" and parsed.simple_paths(channel, node.id)
    }
    return [
        factor for factor, spec in _factors().items() if factor in kinds and spec.scope == "graph"
    ]


def sector_effects(graph, parameters, *, horizon=12) -> list[dict]:
    """Shock of each graph parameter on each sector it reaches, at the central value.

    The same propagation as the calculation (``engine.graph_signal``), read at the horizon
    end, so the analyst sees the shock the positions of that sector will receive.
    """
    from msa.engine.graph_signal import factor_change, factor_signal

    factors = _factors()
    try:
        parsed = TransmissionGraph.model_validate(graph)
    except ValueError:
        return []
    ids = {node.id for node in parsed.nodes}
    effects = []
    for name, spec in (parameters or {}).items():
        try:
            parameter = ScenarioParameter.model_validate(spec)
        except ValidationError:
            continue
        factor = factors.get(parameter.factor)
        if factor is None or factor.scope != "graph":
            continue
        if not parameter.channel or parameter.channel not in ids:
            continue
        macro = parameter.macro()
        sectors = {}
        for node in parsed.nodes:
            if node.kind == "sector" and parsed.simple_paths(parameter.channel, node.id):
                sectors.setdefault(node.okved, node.label)
        for okved, sector in sorted(sectors.items()):
            signal = factor_signal(
                parsed, macro, factor, okved, central_value(macro), horizon, flags=[]
            )
            if signal is None:
                continue
            shock = float(factor_change(factor, signal)[-1])
            if shock == 0:
                continue
            effects.append(
                {
                    "parameter": name,
                    "label": parameter.label,
                    "okved": okved,
                    "sector": sector,
                    "factor": parameter.factor,
                    "shock": shock,
                    "unit": parameter.unit,
                }
            )
    return effects
