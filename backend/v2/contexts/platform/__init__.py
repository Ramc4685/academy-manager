"""Platform bounded context.

Owns SaaS tenant lifecycle, plans, limits, and platform operations.
Academy business contexts may read tenant status through explicit platform
ports, but must not mutate lifecycle state directly.
"""
