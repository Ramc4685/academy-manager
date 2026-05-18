"""Firebase ID token verifier — Anti-Corruption Layer around firebase-admin.

The legacy app already wires Firebase Admin; we reuse the same project/SDK
init but isolate the SDK behind the `TokenVerifier` Protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable


def _load_legacy_verifier() -> Callable[[str], dict[str, object]]:
    try:
        from backend.auth import _verify_firebase_token
    except ModuleNotFoundError:
        from auth import _verify_firebase_token  # type: ignore[no-redef]

    return _verify_firebase_token


class FirebaseTokenVerifier:
    """Real verifier backed by the legacy Firebase verification helper.

    The legacy helper owns production Firebase project configuration and has a
    public-certificate fallback for environments without Admin SDK credentials.
    v2 keeps that infrastructure detail behind this port.
    """

    async def verify(self, id_token: str) -> dict[str, object]:
        # Firebase verification is sync; offload to a thread.
        return await asyncio.to_thread(_load_legacy_verifier(), id_token)
