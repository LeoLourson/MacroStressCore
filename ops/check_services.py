"""Whether an OpenAI-compatible LLM server serves the model a run will ask for."""

import json
from urllib.request import Request, urlopen


def check_llm(base_url, api_key, model):
    """The key is accepted and the model is served: GET {base}/models, as vLLM and DeepSeek."""
    request = Request(
        base_url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"}
    )
    with urlopen(request, timeout=30) as response:
        served = {item["id"] for item in json.load(response)["data"]}
    if model not in served:
        raise RuntimeError(f"Model {model} is not served at {base_url}: {sorted(served)}")
