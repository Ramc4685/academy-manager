"""Shared fake for the student-progress ``CertificateNumbers`` port."""

from __future__ import annotations


class SequentialCertNumbers:
    """Hands out ``T-C-0001``, ``T-C-0002``... like the counter-backed adapter."""

    def __init__(self, prefix: str = "T") -> None:
        self._prefix = prefix
        self._seq = 0

    async def next_number(self) -> str:
        self._seq += 1
        return f"{self._prefix}-C-{self._seq:04d}"
