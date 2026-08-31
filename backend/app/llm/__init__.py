"""The LLM layer (M4) — everything that touches the model, and nothing else.

    buyer text  ->  IntentExtractor  ->  validated BuyerIntent
    model reply ->  validate_tool_arguments  ->  typed tool arguments

This is the **probabilistic side** of the trust boundary ADR-001 draws. Two
properties hold across every module here:

**Nothing in it is trusted.** What comes back from the model is input, not fact.
A `BuyerIntent` is what the model believes the buyer asked for; a `ToolCall` is
something the model would like to happen. Neither carries a price, a SKU, a
stock level or a compatibility claim, and neither authorizes anything. The
deterministic packages — `app.services`, `app.ranking`, `app.repositories`,
`app.domain` — must never import this one, and a standing test enforces that.

**None of it needs an API key to test.** Everything depends on the `LLMClient`
protocol rather than the Anthropic SDK, which is imported by `client.py` alone.
That is what makes M4's exit condition — natural language to validated
structured intent — an ordinary offline unit test.

Two absences are deliberate and load-bearing. There is no `create_order` tool,
at all (ADR-009). And there are no tool *handlers* here: binding a tool to a
service is the agent runtime's job from M5 onward, so what the model may ask for
can be reviewed without reading what happens when it does.
"""

from app.llm.client import DEFAULT_MAX_TOKENS, AnthropicClient, LLMClient, build_client
from app.llm.errors import (
    LLMAuthenticationError,
    LLMError,
    LLMInvalidRequestError,
    LLMOutputError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransportError,
)
from app.llm.extractor import IntentExtractor, merge_intent
from app.llm.models import Message, ModelResponse, Role, StopReason, TokenUsage, ToolCall
from app.llm.prompts import PROMPT_VERSION, PROMPT_VERSIONS, load_system_prompt, prompt_version
from app.llm.schemas import (
    Budget,
    BuyerIntent,
    DeviceReference,
    IntentExtraction,
    ProductRequest,
    loads_decimal,
)
from app.llm.tool_schemas import (
    EXPOSED_TOOL_NAMES,
    FORBIDDEN_TOOL_NAMES,
    READ_ONLY_TOOL_NAMES,
    TOOL_SCHEMAS,
    RiskTier,
    ToolDefinition,
    build_tool_definitions,
    validate_tool_arguments,
)

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "EXPOSED_TOOL_NAMES",
    "FORBIDDEN_TOOL_NAMES",
    "PROMPT_VERSION",
    "PROMPT_VERSIONS",
    "READ_ONLY_TOOL_NAMES",
    "TOOL_SCHEMAS",
    "AnthropicClient",
    "Budget",
    "BuyerIntent",
    "DeviceReference",
    "IntentExtraction",
    "IntentExtractor",
    "LLMAuthenticationError",
    "LLMClient",
    "LLMError",
    "LLMInvalidRequestError",
    "LLMOutputError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMTransportError",
    "Message",
    "ModelResponse",
    "ProductRequest",
    "RiskTier",
    "Role",
    "StopReason",
    "TokenUsage",
    "ToolCall",
    "ToolDefinition",
    "build_client",
    "build_tool_definitions",
    "load_system_prompt",
    "loads_decimal",
    "merge_intent",
    "prompt_version",
    "validate_tool_arguments",
]
