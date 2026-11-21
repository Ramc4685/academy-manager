"""Guard against the #849 trap coming back.

0213 and 0214 re-added global unique ``digest_id`` indexes two months after
#849 closed (fixed by 0244). This replays every migration and fails if a
collection that is tenant-owned (registered in ``TENANT_OWNED_COLLECTIONS``,
or carrying any ``academy_id`` index) gets a unique index whose key lacks
``academy_id``, unless it is listed here with the reason it is global.
Index definitions do not depend on the engine, so the mongomock replay the
drift audit already uses is enough.
"""

from __future__ import annotations

from backend.scripts.index_drift_audit import expected_indexes
from backend.v2.tests.test_no_raw_tenant_mongo_access import TENANT_OWNED_COLLECTIONS

GLOBAL_UNIQUE_BY_DESIGN: dict[str, str] = {
    "academy_connected_accounts.academy_connected_accounts_stripe_account": (
        "A Stripe account id belongs to exactly one academy."
    ),
    "billing_settings.billing_settings_invoice_number_prefix_unique": (
        "Invoice prefixes are unique across academies on purpose (0206)."
    ),
    "message_deliveries.message_deliveries_provider_message_id_unique": (
        "Provider-issued id, globally unique by construction (#849 note A)."
    ),
    "platform_audit_events.audit_event_id_unique": "Platform audit trail, not tenant data.",
    "platform_tenant_subscriptions.platform_tenant_subscriptions_id_unique": "Platform billing.",
    "platform_tenant_subscriptions.platform_tenant_subscriptions_stripe_subscription_unique": (
        "Platform billing; a Stripe subscription id is global."
    ),
    "push_devices.push_devices_token_unique": "A device token belongs to one device (0215).",
    "stripe_webhook_events.event_id_unique": "Stripe event ids; no tenant at ingest.",
    "student_data_deletion_requests.student_data_deletion_requests_id_unique": "Platform ops.",
    "support_access_grants.support_access_grants_id_unique": "Platform ops.",
    "support_impersonation_requests.support_impersonation_requests_id_unique": "Platform ops.",
    "tenant_deletion_requests.tenant_deletion_requests_id_unique": "Platform ops.",
    "tenant_export_requests.tenant_export_requests_id_unique": "Platform ops.",
}


def _fields(index: dict) -> list[str]:  # type: ignore[type-arg]
    return [pair[0] for pair in index["key"]]


async def _global_uniques_on_tenant_collections() -> set[str]:
    found: set[str] = set()
    for collection, indexes in (await expected_indexes()).items():
        tenant_owned = collection in TENANT_OWNED_COLLECTIONS or any(
            "academy_id" in _fields(index) for index in indexes.values()
        )
        if not tenant_owned:
            continue
        for name, index in indexes.items():
            if name != "_id_" and index.get("unique") and "academy_id" not in _fields(index):
                found.add(f"{collection}.{name}")
    return found


async def test_no_tenant_collection_has_an_unexplained_global_unique_index() -> None:
    unexplained = await _global_uniques_on_tenant_collections() - set(GLOBAL_UNIQUE_BY_DESIGN)

    assert not unexplained, (
        "Unique index without academy_id on a tenant-owned collection (the #849 trap). "
        "Scope it as (academy_id, <id>) with a {'<id>': {'$gt': ''}} partial filter, or "
        f"add it to GLOBAL_UNIQUE_BY_DESIGN with the reason: {sorted(unexplained)}"
    )


async def test_every_allowlisted_index_still_exists() -> None:
    stale = set(GLOBAL_UNIQUE_BY_DESIGN) - await _global_uniques_on_tenant_collections()

    assert not stale, f"Remove stale GLOBAL_UNIQUE_BY_DESIGN entries: {sorted(stale)}"
