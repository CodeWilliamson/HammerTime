"""HammerTime — curling rink draw timer (Python port of the original Node server).

Single source of truth for the application/schema version. This value gates which
files in ``db_migrations/`` get applied (same rule as the Node ``package.json``).

Keep it at a version that is >= the deployed ``schema_version``; bump it whenever a
new migration file is added.
"""

__version__ = "2.0.0"
