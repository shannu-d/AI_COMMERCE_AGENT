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

**Phase 2 — commerce (M6).** Designed at column level in ADR-006 and not
implemented: ``sessions``, ``session_messages``, ``carts``, ``cart_items``,
``approvals``, ``idempotency_keys``, ``orders``, ``order_items``, ``payments``,
``webhook_events``, ``audit_events``. D§36 and D§39 explicitly exclude them from
the first catalog milestone.
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

__all__ = [
    "CATALOG_TABLES",
    "COMPATIBILITY_RULE_TYPES",
    "COMPATIBILITY_TARGET_KINDS",
    "COMPATIBILITY_TARGET_TYPES",
    "PRODUCT_RELATIONSHIP_TYPES",
    "Category",
    "CompatibilityRule",
    "CompatibilityTarget",
    "Inventory",
    "Merchant",
    "Product",
    "ProductRelationship",
    "ProductVariant",
]
