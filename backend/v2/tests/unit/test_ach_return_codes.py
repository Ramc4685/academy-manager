from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    _stripe_failure_to_nacha_return_code,
)
from backend.v2.contexts.billing.domain.ach_returns import normalize_nacha_return_code


def test_maps_known_stripe_bank_failure_codes_to_nacha_return_codes() -> None:
    assert _stripe_failure_to_nacha_return_code("insufficient_funds") == "R01"
    assert _stripe_failure_to_nacha_return_code("account_closed") == "R02"
    assert _stripe_failure_to_nacha_return_code("no_account") == "R03"


def test_normalizes_explicit_nacha_return_code_values() -> None:
    assert normalize_nacha_return_code("ach_return_r01") == "R01"
    assert normalize_nacha_return_code("r03") == "R03"
    assert normalize_nacha_return_code("insufficient_funds") is None
