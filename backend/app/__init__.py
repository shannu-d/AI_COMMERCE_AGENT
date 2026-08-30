"""Merchant AI Commerce Agent — backend application.

Package layout follows docs/analysis/05-proposed-repo-structure.md, and the
separation is load-bearing rather than cosmetic (ADR-001):

    app/db/           SQLAlchemy models and session management
    app/repositories/ data access                          (M2)
    app/services/     deterministic domain services        (M2)
    app/ranking/      deterministic recommendation engine  (M3)
    app/llm/          Claude client and schemas            (M4)   probabilistic
    app/agent/        agent runtime, tools, registry       (M5)   probabilistic
    app/policy/       deterministic policy engine          (M9)
    app/payments/     Razorpay client and webhooks         (M11)
    app/api/          FastAPI routes
    app/seed/         catalog seed data and loader

Deterministic packages MUST NOT import from ``app.llm`` or ``app.agent``. The
model proposes; deterministic code decides.
"""

__version__ = "0.1.0"
