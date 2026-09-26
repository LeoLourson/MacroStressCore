"""msa.reporting.trace.trace_number: resolving a cited number back to its journal lineage."""

import pytest

from msa.graph.interrupts import start_run
from msa.platform.registry import registry
from msa.reporting.trace import trace_number

from ..support import agents, confirm, run_input


def test_trace_number_resolves_a_position_metric_path(graph_factory):
    graph, journal = graph_factory(agents=agents(calculate=True))
    start_run(graph, run_input("trace1"))
    state = confirm(graph, "trace1")
    numbers = state["report"]["numbers"]
    path = next(n["metric_path"] for n in numbers if n["metric_path"].startswith("/positions/"))

    traced = trace_number("trace1", path, journal, registry=registry())

    assert traced["metric_path"] == path
    assert traced["value"] is not None
    assert traced["sources"]
    assert traced["lineage"]


def test_trace_number_resolves_a_portfolio_slice_path(graph_factory):
    graph, journal = graph_factory(agents=agents(calculate=True))
    start_run(graph, run_input("trace2"))
    state = confirm(graph, "trace2")
    numbers = state["report"]["numbers"]
    path = next(n["metric_path"] for n in numbers if n["metric_path"].startswith("/portfolio/"))

    traced = trace_number("trace2", path, journal, registry=registry())

    assert traced["metric_path"] == path
    assert traced["value"] is not None
    # A portfolio-level number is not tied to one position's upstream lineage.
    assert not path.startswith("/positions/")


def test_trace_number_unknown_metric_path_raises_keyerror(graph_factory):
    graph, journal = graph_factory(agents=agents(calculate=True))
    start_run(graph, run_input("trace3"))
    confirm(graph, "trace3")

    with pytest.raises(KeyError):
        trace_number("trace3", "/positions/nope/metrics/nope/p50", journal, registry=registry())


def test_trace_number_unknown_run_raises_keyerror(graph_factory):
    _, journal = graph_factory()
    with pytest.raises(KeyError):
        trace_number("no-such-run", "/positions/x/metrics/y/p50", journal, registry=registry())
