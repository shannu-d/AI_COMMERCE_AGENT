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

**Phase 2 - commerce (M6).** The nine tables ADR-006 designs at column level,
created by migration ``0004``:

===========================  ========================================
``carts``, ``cart_items``    the working set; totals backend-computed
``approvals``                the authorization artefact (ADR-007)
``idempotency_keys``         replay safety for order creation (ADR-013)
``orders``, ``order_items``  the immutable financial record
``payments``                 written only from a verified webhook
``webhook_events``           raw body, and the dedupe constraint
``audit_events``             append-only; the durable record
===========================  ========================================

The load-bearing one is ``orders.approval_id NOT NULL``: the database itself
refuses to store an unapproved order.

**Phase 3 - identity (ADR-023).** ``users`` and ``auth_tokens``, created by
migration ``0005``, plus one nullable ``sessions.user_id``. Ownership of a cart
or an order is *derived* through that column rather than stored on either table,
so authentication cost the commerce schema no data migration.

``merchant_activity`` (migration ``0006``) records what an administrator changed
in the dashboard. It is deliberately not ``audit_events``: that table
reconstructs one transaction and hangs off a session, cart, order or payment,
none of which a price edit has.
"""

from app.db.models.activity import MerchantActivity
from app.db.models.approval import Approval
from app.db.models.cart import Cart, CartItem
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
from app.db.models.order import IdempotencyKey, Order, OrderItem
from app.db.models.payment import AuditEvent, Payment, WebhookEvent
from app.db.models.product import Product
from app.db.models.relationship import PRODUCT_RELATIONSHIP_TYPES, ProductRelationship
from app.db.models.session import SESSION_MESSAGE_ROLES, Session, SessionMessage
from app.db.models.user import AuthToken, User
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

#: The two tables ADR-023 adds. Deliberately their own group rather than
#: appended to ``SESSION_TABLES``: identity is not conversation state, and the
#: schema guard should say *when* and *why* each table arrived rather than
#: accumulating a single undifferentiated list.
IDENTITY_TABLES: tuple[str, ...] = ("users", "auth_tokens", "merchant_activity")

#: The nine tables M6 adds, in dependency order.
COMMERCE_TABLES: tuple[str, ...] = (
    "carts",
    "cart_items",
    "approvals",
    "idempotency_keys",
    "orders",
    "order_items",
    "payments",
    "webhook_events",
    "audit_events",
)

__all__ = [
    "CATALOG_TABLES",
    "COMMERCE_TABLES",
    "COMPATIBILITY_RULE_TYPES",
    "COMPATIBILITY_TARGET_KINDS",
    "COMPATIBILITY_TARGET_TYPES",
    "IDENTITY_TABLES",
    "PRODUCT_RELATIONSHIP_TYPES",
    "SESSION_MESSAGE_ROLES",
    "SESSION_TABLES",
    "Approval",
    "AuditEvent",
    "AuthToken",
    "Cart",
    "CartItem",
    "Category",
    "CompatibilityRule",
    "CompatibilityTarget",
    "IdempotencyKey",
    "Inventory",
    "Merchant",
    "MerchantActivity",
    "Order",
    "OrderItem",
    "Payment",
    "Product",
    "ProductRelationship",
    "ProductVariant",
    "Session",
    "SessionMessage",
    "User",
    "WebhookEvent",
]
