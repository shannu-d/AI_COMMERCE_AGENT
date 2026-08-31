"""Tool handlers: the business logic behind each registered tool (ADR-009).

One module per concern rather than one per tool, because `check_inventory` and
`get_upsell_candidates` share the stock reasoning and `search_catalog` and
`get_product` share the catalog.

Every handler has the same shape — `(context, memory, validated_args) -> dict` —
which is what lets `executor.py` implement the A§19 pipeline once. By the time a
handler runs, the arguments have already been schema-validated and the tool has
already been authorized; a handler contains business logic and nothing else.

**There is no `create_order.py`, and there must never be one** (ADR-009, closing
D6). Order creation is a user-initiated API path behind the Policy Engine. A
standing test asserts no module here is named for a forbidden tool.
"""

from app.agent.tools.catalog import get_product, search_catalog
from app.agent.tools.compatibility import get_compatible_products, resolve_device
from app.agent.tools.inventory import check_inventory, get_upsell_candidates

__all__ = [
    "check_inventory",
    "get_compatible_products",
    "get_product",
    "get_upsell_candidates",
    "resolve_device",
    "search_catalog",
]
