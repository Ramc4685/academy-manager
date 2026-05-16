"""Composition root.

This package is the one place that imports across contexts — wiring use
cases to their cross-context ports (e.g., Coaching's SessionLookup is
implemented by a tiny adapter over Enrollment's SessionQuery). Per
ADR-0005, only ``main.py`` and ``composition/`` are allowed to do this.
"""
