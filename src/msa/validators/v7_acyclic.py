from collections import deque

from msa.contracts.graph import TransmissionGraph

from .base import Verdict


class AcyclicValidator:
    def check(self, payload):
        data = (
            payload.model_dump(mode="json") if isinstance(payload, TransmissionGraph) else payload
        )
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("nodes"), list)
            or not isinstance(data.get("edges"), list)
        ):
            return []
        nodes = {n.get("id") for n in data["nodes"] if isinstance(n, dict)}
        if None in nodes or len(nodes) != len(data["nodes"]):
            return []
        indegree = dict.fromkeys(nodes, 0)
        children = {n: [] for n in nodes}
        for edge in data["edges"]:
            if (
                not isinstance(edge, dict)
                or edge.get("src") not in nodes
                or edge.get("dst") not in nodes
            ):
                return []
            indegree[edge["dst"]] += 1
            children[edge["src"]].append(edge["dst"])
        queue = deque(n for n, degree in indegree.items() if degree == 0)
        count = 0
        while queue:
            count += 1
            for child in children[queue.popleft()]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        return [
            Verdict(
                ok=count == len(nodes),
                rule_id="V7",
                path="/edges",
                message="Graph is acyclic" if count == len(nodes) else "Graph has a cycle",
            )
        ]
