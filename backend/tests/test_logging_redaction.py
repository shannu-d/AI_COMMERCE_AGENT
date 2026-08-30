"""Log redaction.

architecture.md L§42/L§45 and A§45 require that secrets never reach a log. The
filter is tested directly because it is the mechanism that has to hold when a
contributor logs something careless.
"""

from __future__ import annotations

import json
import logging

from app.logging_config import REDACTED, ConsoleFormatter, JsonFormatter, RedactionFilter


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_configured_secret_is_masked_in_the_message() -> None:
    filt = RedactionFilter(["rzp_test_supersecretvalue"])
    record = _record("calling razorpay with key rzp_test_supersecretvalue")

    filt.filter(record)

    assert "rzp_test_supersecretvalue" not in record.getMessage()
    assert REDACTED in record.getMessage()


def test_configured_secret_is_masked_in_a_structured_field() -> None:
    filt = RedactionFilter(["whsec_averylongwebhooksecret"])
    record = _record("webhook received", detail="signature=whsec_averylongwebhooksecret")

    filt.filter(record)

    assert "whsec_averylongwebhooksecret" not in record.detail
    assert REDACTED in record.detail


def test_secret_looking_field_names_are_masked_even_when_unconfigured() -> None:
    """The second mechanism: a field nobody registered as a secret."""
    filt = RedactionFilter([])
    record = _record(
        "outbound call",
        api_key="anything-at-all",
        authorization="Bearer abc",
        webhook_signature="deadbeef",
        password="hunter2",
        product_id="not-a-secret",
    )

    filt.filter(record)

    assert record.api_key == REDACTED
    assert record.authorization == REDACTED
    assert record.webhook_signature == REDACTED
    assert record.password == REDACTED
    assert record.product_id == "not-a-secret"


def test_short_values_are_not_used_as_masks() -> None:
    """A two-character 'secret' would corrupt unrelated log text."""
    filt = RedactionFilter(["ab"])
    record = _record("about to search the catalog")

    filt.filter(record)

    assert record.getMessage() == "about to search the catalog"


def test_json_formatter_emits_one_object_with_extras() -> None:
    record = _record("policy evaluated", decision="FAIL", reason_codes=["PRICE_CHANGED"])

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "policy evaluated"
    assert payload["level"] == "INFO"
    assert payload["decision"] == "FAIL"
    assert payload["reason_codes"] == ["PRICE_CHANGED"]


def test_console_formatter_renders_extras() -> None:
    record = _record("cart updated", cart_version=8)

    rendered = ConsoleFormatter().format(record)

    assert "cart updated" in rendered
    assert "cart_version=8" in rendered


def test_filter_and_formatter_compose() -> None:
    """The end-to-end path a real log call takes."""
    filt = RedactionFilter(["sk-ant-a-very-long-secret"])
    record = _record("llm call", api_key="sk-ant-a-very-long-secret", model="claude-sonnet-5")

    filt.filter(record)
    payload = json.loads(JsonFormatter().format(record))

    assert payload["api_key"] == REDACTED
    assert payload["model"] == "claude-sonnet-5"
    assert "sk-ant-a-very-long-secret" not in json.dumps(payload)
