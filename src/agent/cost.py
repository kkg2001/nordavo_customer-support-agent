import json
from pathlib import Path
from .llm import Usage

_PRICING = Path(__file__).resolve().parents[2] / "pricing.json"


def cost_usd(model: str, usage: Usage) -> float:
    prices = json.loads(_PRICING.read_text())
    p = prices.get(model)
    if not p:
        return 0.0
    return (usage.input_tokens * p["input"] + usage.output_tokens * p["output"]) / 1_000_000
