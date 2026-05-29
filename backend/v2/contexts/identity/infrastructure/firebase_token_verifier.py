"""Firebase ID token verifier backed by the v2 Firebase Admin adapter."""

from __future__ import annotations

import asyncio

from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import (
    get_firebase_admin_adapter,
)


class FirebaseTokenVerifier:
    """Real verifier backed by v2 Firebase Admin infrastructure."""

    async def verify(self, id_token: str) -> dict[str, object]:
        # Firebase verification is sync; offload to a thread.
        return await asyncio.to_thread(get_firebase_admin_adapter().verify_id_token, id_token)
