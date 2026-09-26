from msa.engine.catalog import describe_model as describe
from msa.engine.catalog import list_models as catalog
from msa.engine.catalog import run_model as calculate

from ..audit import CallContext


def register(tool, services):
    @tool
    def run_model(model_id: str, payload: dict, audit: CallContext) -> dict:
        """Execute a registered pure model on prepared inputs and the run's scenario set."""
        return calculate(model_id, payload).model_dump(mode="json")

    @tool
    def list_models(audit: CallContext) -> list[dict]:
        """The registered calculation models: what they calculate and report."""
        return [
            {
                key: item[key]
                for key in (
                    "model_id",
                    "version",
                    "label",
                    "instrument_types",
                    "metrics",
                    "slices",
                    "plugin_id",
                )
            }
            for item in catalog()
        ]

    @tool
    def describe_model(model_id: str, audit: CallContext) -> dict:
        """One model: its metrics with units and labels, limits and the version of its code."""
        item = describe(model_id)
        item.pop("input_schema", None)
        return item
