"""ORM models.

Importing this package registers every table on ``Base.metadata``. Alembic's
``env.py`` imports it for exactly that reason, so a model that is not re-exported
here is invisible to autogenerate.

**Phase 1 — catalog (M1).** The seven tables architecture.md D§4–D§16 specifies
at column level, created by migration ``0001``:

===========================  ========================================
``merchants``                who owns the catalog
``categories``               hierarchical product categories
``products``                 the conceptual product
``product_variants``         the sellable unit: SKU, price, currency
``inventory``                stock, per variant
``compatibility_rules``      what a product works with
``product_relationships``    cross-sell, bundle, related
===========================  ========================================

Plus one table the specification does not define, created by migration ``0002``
and kept separate so the specified schema stays auditable in isolation:

===========================  ========================================
``compatibility_targets``    the identifier vocabulary that makes
                             compatibility resolvable without guessing
                             (ADR-003)
===========================  ========================================

**Conversation state (M5).** ``sessions`` and ``session_messages``, created by
migration ``0003``. ADR-006 designs them alongside the commerce tables, but open
question C3 is closed as *PostgreSQL* and the task breakdown gives AGENT-01 - the
M5 runtime skeleton - the job of closing it, which a dictionary cannot do. They
carry no money, no cart and no approval, so the D§36/D§39 line still holds.

**Phase 2 - commerce (M6).** Designed at column level in ADR-006 and not
implemented: ``carts``, ``cart_items``, ``approvals``, ``idempotency_keys``,
``orders``, ``order_items``, ``payments``, ``webhook_events``, ``audit_events``.
D§36 and D§39 explicitly exclude them from the first catalog milestone.
"""

from app.db.models.category import Category
from app.db.models.compatibility import (
    COMPATIBILITY_RULE_TYPES,
    COMPATIBILITY_TARGET_TYPES,
    CompatibilityRule,
)
from app.db.models.compatibility_target import (
    COMPATIBILITY_TARGET_KINDS,
    CompatibilityTarget,
)
from app.db.models.inventory import Inventory
from app.db.models.merchant import Merchant
from app.db.models.product import Product
from app.db.models.relationship import PRODUCT_RELATIONSHIP_TYPES, ProductRelationship
from app.db.models.session import SESSION_MESSAGE_ROLES, Session, SessionMessage
from app.db.models.variant import ProductVariant

#: The seven tables architecture.md specifies, in dependency order.
CATALOG_TABLES: tuple[str, ...] = (
    "merchants",
    "categories",
    "products",
    "product_variants",
    "inventory",
    "compatibility_rules",
    "product_relationships",
)

#: The two tables M5 adds. Not part of ``CATALOG_TABLES``: they are conversation
#: state, not catalog.
SESSION_TABLES: tuple[str, ...] = ("sessions", "session_messages")

__all__ = [
    "CATALOG_TABLES",
    "COMPATIBILITY_RULE_TYPES",
    "COMPATIBILITY_TARGET_KINDS",
    "COMPATIBILITY_TARGET_TYPES",
    "PRODUCT_RELATIONSHIP_TYPES",
    "SESSION_MESSAGE_ROLES",
    "SESSION_TABLES",
    "Category",
    "CompatibilityRule",
    "CompatibilityTarget",
    "Inventory",
    "Merchant",
    "Product",
    "ProductRelationship",
    "ProductVariant",
    "Session",
    "SessionMessage",
]
