"""Lakebase Autoscaling connection details and credential minting.

Shared by the migration runner and (from step (b)) the connection pool, so the
credential call lives in exactly one place.

Two things this module is careful about:

* **The injected environment is the only source.** Attaching the Lakebase project
  as an app resource injects PGHOST/PGPORT/PGDATABASE/PGUSER/PGSSLMODE/
  ENDPOINT_NAME. Those names are used verbatim — never copied into PG_HOST-style
  aliases, never defaulted over, and never reconstructed from the SDK. There is
  deliberately no discovery fallback: anything that fills in a missing host is
  something that can disagree with the attached resource without saying so.

* **The credential API is the Autoscaling one.** ``databricks-sdk`` defines
  ``generate_database_credential`` twice, on two different services, returning two
  different classes that happen to share a name::

      w.postgres.generate_database_credential(endpoint=...)           # Autoscaling  <- this one
      w.database.generate_database_credential(instance_names=[...])   # instances

  We are projects/branches/endpoints, so it is ``w.postgres``. Its credential
  carries ``expire_time`` (a protobuf Timestamp); the *other* class carries
  ``expiration_time`` (an ISO string). Reaching for the wrong attribute fails at
  runtime inside the connect hook, roughly an hour after a green deploy.

Verified against databricks-sdk 0.127.0::

    generate_database_credential(endpoint: str, *, claims=None, expire_time=None,
                                 group_name=None, ttl=None) -> DatabaseCredential
    DatabaseCredential(expire_time, token)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from databricks.sdk import WorkspaceClient

# Injected by the attached Lakebase project resource. All six are required.
INJECTED_VARS = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGSSLMODE", "ENDPOINT_NAME")


@dataclass(frozen=True)
class PgSettings:
    host: str
    port: str
    database: str
    user: str          # the app service principal's DATABRICKS_CLIENT_ID
    sslmode: str
    endpoint_name: str  # projects/<project-id>/branches/<branch-id>/endpoints/<endpoint-id>

    def sqlalchemy_url(self) -> str:
        """DSN without a password — that is minted per physical connection."""
        return (
            f"postgresql+psycopg://{self.user}@{self.host}:{self.port}"
            f"/{self.database}?sslmode={self.sslmode}"
        )

    def psycopg_kwargs(self) -> dict[str, str]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "sslmode": self.sslmode,
        }


_workspace: WorkspaceClient | None = None


def workspace() -> WorkspaceClient:
    global _workspace
    if _workspace is None:
        _workspace = WorkspaceClient()
    return _workspace


def resolve_settings() -> PgSettings:
    """Read connection details from the injected environment.

    Raises if any variable is missing. In a deployed App all six are present and
    this is a pure environment read; to run migrations from a workstation, export
    the same six names from the attached resource.
    """
    missing = [name for name in INJECTED_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Lakebase environment is incomplete; missing "
            f"{missing}. These are injected by the attached Lakebase project "
            "resource and are the only supported source of connection details; "
            "there is no fallback, because a value guessed here could disagree "
            "with the real endpoint without any error. To run migrations locally, "
            f"export all of: {', '.join(INJECTED_VARS)}"
        )
    return PgSettings(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        database=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        sslmode=os.environ["PGSSLMODE"],
        endpoint_name=os.environ["ENDPOINT_NAME"],
    )


def mint_password(settings: PgSettings) -> str:
    """Mint a short-lived OAuth token to use as the Postgres password."""
    credential = workspace().postgres.generate_database_credential(
        endpoint=settings.endpoint_name
    )
    token = credential.token
    if not token:
        # token is Optional[str]. Unguarded, a failed mint reaches psycopg as an
        # opaque authentication failure instead of pointing at the mint itself.
        raise RuntimeError(
            "generate_database_credential returned no token for endpoint "
            f"{settings.endpoint_name}"
        )
    return token
