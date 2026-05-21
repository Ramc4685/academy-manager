from backend.v2.shared.ids import new_ulid


def test_new_ulid_returns_canonical_string() -> None:
    value = new_ulid()

    assert len(value) == 26
    assert value == value.upper()
