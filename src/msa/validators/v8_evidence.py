from msa.contracts.graph import TransmissionGraph

from .base import Verdict


class EvidenceValidator:
    def check(self, payload):
        data = (
            payload.model_dump(mode="json") if isinstance(payload, TransmissionGraph) else payload
        )
        if not isinstance(data, dict) or not isinstance(data.get("edges"), list):
            return []
        missing = [
            i
            for i, edge in enumerate(data["edges"])
            if isinstance(edge, dict) and not edge.get("evidence")
        ]
        return [
            Verdict(
                ok=False,
                rule_id="V8",
                path=f"/edges/{i}/evidence",
                message="Every edge needs at least one source",
            )
            for i in missing
        ] or [Verdict(ok=True, rule_id="V8", path="/edges", message="Every edge has a source")]
