from typing import Dict
from src.config import ModelEndpointConfig

class CostCalculator:
    """
    Calculates exact per-request USD token cost across prompt and completion tokens
    for each configured LLM provider and model tier.
    """
    def __init__(self, models: list[ModelEndpointConfig]):
        self._pricing: Dict[str, tuple[float, float]] = {
            m.id: (m.cost_per_1k_prompt_tokens, m.cost_per_1k_completion_tokens)
            for m in models
        }

    def calculate_cost(
        self, model_id: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        prompt_rate, completion_rate = self._pricing.get(model_id, (0.001, 0.002))
        cost = (prompt_tokens / 1000.0) * prompt_rate + (
            completion_tokens / 1000.0
        ) * completion_rate
        return round(cost, 6)
