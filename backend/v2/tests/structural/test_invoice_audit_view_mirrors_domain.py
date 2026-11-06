"""The admin audit view copies BillingAuditEntry because interfaces may not import domain.

A new domain field would otherwise be silently dropped from the API response.
"""

from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.interfaces.admin.billing_routes import InvoiceAuditEntryView


def test_invoice_audit_view_has_every_domain_field() -> None:
    assert set(InvoiceAuditEntryView.model_fields) == set(BillingAuditEntry.model_fields)
