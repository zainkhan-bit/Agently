"""The models this server may use, with their limits and prices.

Read from Google's documentation on 2026-11-25. Promotional prices are ignored: the higher, later
price is used. A model that is not listed cannot be configured.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    max_input_tokens: int
    max_output_tokens: int  # thinking included
    # Nano-dollars per token: $1 per million tokens is 1,000.
    input_price: int
    output_price: int  # also thinking
    streaming: bool
    thinking_level: str  # the lowest the model supports: drafts need speed, and thinking costs

    def cost(self, input_tokens: int, output_tokens: int) -> int:
        """In nano-dollars."""
        return input_tokens * self.input_price + output_tokens * self.output_price


GEMINI_MODELS = {
    spec.name: spec
    for spec in (
        ModelSpec("gemini-3.5-flash-lite", 1_048_576, 65_536, 300, 2_500, True, "MINIMAL"),
        ModelSpec("gemini-3.8-flash", 1_048_576, 65_536, 1_500, 7_500, True, "LOW"),
    )
}
