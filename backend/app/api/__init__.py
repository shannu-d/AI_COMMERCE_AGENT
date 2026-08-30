"""FastAPI layer.

Route handlers translate HTTP to service calls and back. Business logic lives in
``app.services``, ``app.ranking`` and ``app.policy`` — never here (Phase-5
quality rule: keep business logic out of route handlers).
"""
