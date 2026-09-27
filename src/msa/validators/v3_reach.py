"""V3: every mechanism the event starts reaches the portfolio.

A channel or sector the event reaches must lead on to a factor node: a chain that stops
there moves no model input, so the calculation silently ignores the mechanism. A node the
event does not reach (its edges removed in review) is inert and is not flagged.
"""

from collections import deque

from msa.contracts.graph import TransmissionGraph

from .base import Verdict


def _reached(start, links):
    seen, queue = set(start), deque(start)
    while queue:
        for following in links.get(queue.popleft(), ()):
            if following not in seen:
                seen.add(following)
                queue.append(following)
    return seen


class ReachValidator:
    def check(self, payload):
        try:
            graph = (
                payload
                if isinstance(payload, TransmissionGraph)
                else TransmissionGraph.model_validate(payload)
            )
        except ValueError:
            return []  # V1 owns malformed graphs.
        children, parents = {}, {}
        for edge in graph.edges:
            children.setdefault(edge.src, []).append(edge.dst)
            parents.setdefault(edge.dst, []).append(edge.src)
        from_event = _reached([graph.event_id], children)
        to_factor = _reached([n.id for n in graph.nodes if n.kind == "factor"], parents)
        verdicts = []
        for node in graph.nodes:
            if node.kind not in {"channel", "sector"}:
                continue
            if node.id not in from_event or node.id in to_factor:
                continue
            entry = next(
                i
                for i, edge in enumerate(graph.edges)
                if edge.dst == node.id and edge.src in from_event
            )
            verdicts.append(
                Verdict(
                    ok=False,
                    rule_id="V3",
                    path=f"/edges/{entry}",
                    message=(
                        f"The {node.kind} {node.id!r} leads to no factor node, so it moves no "
                        "position. Continue it through the portfolio's sectors to the factors "
                        "it changes, or remove it with its edges if no position is exposed."
                    ),
                )
            )
        return verdicts or [
            Verdict(ok=True, rule_id="V3", path="/edges", message="Every chain reaches a factor")
        ]
