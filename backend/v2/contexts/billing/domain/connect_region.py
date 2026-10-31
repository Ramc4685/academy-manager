"""Where an academy's Stripe connected account is created, and in what currency.

The country and default currency of a new connected account come from the
academy record (``country`` / ``currency``; absent means US / USD). Only US
academies billing in USD are supported today: invoices, prices and Stripe
charges are all USD, so an account in any other region would be created in a
currency the app never charges in. Refuse it instead of creating it.

Pure domain. No infra imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.billing.domain.errors import UnsupportedConnectAccountRegion

DEFAULT_COUNTRY = "US"
DEFAULT_CURRENCY = "USD"
SUPPORTED_COUNTRY = "US"
SUPPORTED_CURRENCY = "USD"


def _normalise(value: object, default: str) -> str:
    text = str(value).strip().upper() if value is not None else ""
    return text or default


@dataclass(frozen=True)
class ConnectAccountRegion:
    """ISO country code and ISO currency code, both upper case."""

    country: str
    currency: str

    @classmethod
    def from_stored(cls, *, country: object, currency: object) -> ConnectAccountRegion:
        """Build from raw academy-record values: blank or absent -> US / USD."""
        return cls(
            country=_normalise(country, DEFAULT_COUNTRY),
            currency=_normalise(currency, DEFAULT_CURRENCY),
        )

    def require_supported(self) -> None:
        """Raise ``UnsupportedConnectAccountRegion`` unless this is US / USD."""
        if self.country == SUPPORTED_COUNTRY and self.currency == SUPPORTED_CURRENCY:
            return
        raise UnsupportedConnectAccountRegion(
            "Stripe accounts can only be created for academies in the US billing in USD "
            f"today (academy has country={self.country}, currency={self.currency})",
            country=self.country,
            currency=self.currency,
        )
