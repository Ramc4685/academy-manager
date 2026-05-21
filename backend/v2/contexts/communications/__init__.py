"""Communications bounded context.

Owns campaigns, per-recipient deliveries, audience targeting, and reminder
templates. See ADR-0007 and `docs/requirements/2026-05-21-saas-data-model-
architecture-assessment.md` section "Messaging Needs Audience And Delivery
Records".

The thin DM/announcement CRUD in `backend/v2/shared/comms/messages.py` is
retained for now; it stores chat-style 1:1 and broadcast messages without
audience targeting or delivery tracking. This context owns the richer
campaign/delivery model.
"""
