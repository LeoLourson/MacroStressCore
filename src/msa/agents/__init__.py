"""The run's core agents. Clients and connections live here and never enter the run state."""

from dataclasses import dataclass

from .base import Agent


@dataclass(frozen=True)
class Agents:
    ingest: Agent
    causal: Agent
    exposure: Agent
    draw_macro: Agent
    quant: Agent
    aggregate: Agent
    advisory: Agent


def build_agents(
    *,
    llm,
    mock_llm: bool,
    registry,
    resolver,
    thresholds_repository,
    original_store,
    options: dict,
    tools=None,
    estimate_scenario: bool = False,
) -> Agents:
    """The production line: the LLM agents, the models per position and the portfolio.

    ``resolver`` reads the run's snapshot (``mcp-portfolio`` in a run); ``tools`` routes the
    model runs through ``mcp-models`` so each calculation is an audited tool call; ``options``
    are the namespace's run options of the plugins (the credit calibration in force).
    """
    from .advisory import AdvisoryAgent
    from .aggregate import AggregateAgent
    from .causal import CausalAgent
    from .draw_macro import DrawMacroAgent
    from .exposure import ExposureAgent
    from .ingest import IngestAgent
    from .quant import QuantAgent

    return Agents(
        ingest=IngestAgent(store=original_store),
        causal=CausalAgent(llm=llm, mock=mock_llm, estimate_scenario=estimate_scenario),
        exposure=ExposureAgent(registry=registry, resolver=resolver),
        draw_macro=DrawMacroAgent(registry=registry),
        quant=QuantAgent(registry=registry, tools=tools),
        aggregate=AggregateAgent(registry=registry),
        advisory=AdvisoryAgent(
            registry=registry,
            thresholds_repository=thresholds_repository,
            llm=llm,
            options=options,
        ),
    )
