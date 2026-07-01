from backend.v2.contexts.billing.domain.ach_returns import ach_return_code_from_stripe_object


def test_maps_known_stripe_bank_failure_codes_to_nacha_return_codes() -> None:
    assert ach_return_code_from_stripe_object({"failure_code": "insufficient_funds"}) == "R01"
    assert ach_return_code_from_stripe_object({"failure_code": "account_closed"}) == "R02"
    assert ach_return_code_from_stripe_object({"failure_code": "no_account"}) == "R03"


def test_extracts_explicit_r_code_from_nested_payment_error_or_metadata() -> None:
    assert (
        ach_return_code_from_stripe_object(
            {"last_payment_error": {"decline_code": "ach_return_r01"}}
        )
        == "R01"
    )
    assert ach_return_code_from_stripe_object({"metadata": {"ach_return_code": "r03"}}) == "R03"
