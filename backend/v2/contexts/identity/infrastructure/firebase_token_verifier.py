"""Firebase ID token verifier — Anti-Corruption Layer around firebase-admin.

The legacy app already wires Firebase Admin; we reuse the same project/SDK
init but isolate the SDK behind the `TokenVerifier` Protocol.
"""

from __future__ import annotations

import asyncio
from typing import Any


class FirebaseTokenVerifier:
    """Real verifier. Uses firebase-admin lazily to avoid forcing a hard
    dependency at import time (tests use a fake verifier).
    """

    def __init__(self) -> None:
        self._initialized = False
        self._auth: Any | None = None

    def _lazy_init(self) -> None:
        if self._initialized:
            return
        # firebase_admin is initialized by the legacy auth module; if it
        # isn't, we initialize a default app.
        import firebase_admin  # type: ignore[import-not-found]
        from firebase_admin import auth as fa_auth  # type: ignore[import-not-found]

        if not firebase_admin._apps:  # pragma: no cover - depends on legacy init order
            firebase_admin.initialize_app()
        self._auth = fa_auth
        self._initialized = True

    async def verify(self, id_token: str) -> dict[str, object]:
        self._lazy_init()
        assert self._auth is not None
        # firebase-admin.auth.verify_id_token is sync; offload to a thread.
        return await asyncio.to_thread(self._auth.verify_id_token, id_token)
