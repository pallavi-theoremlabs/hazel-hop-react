"""Lakebase Autoscaling connection details and credential minting.

Shared by the migration runner and (from step (b)) the connection pool, so the
credential call lives in exactly one place.

Two things this module is careful about:

* **The environment is the only source.** Attaching the Lakebase project as an app
  resource injects PGHOST/PGPORT/PGDATABASE/PGUSER/PGSSLMODE — five variables, not
  six. It does **not** inject ENDPOINT_NAME; app.yaml sets that one explicitly.
  This was settled by a deploy, not by documentation: with no ENDPOINT_NAME entry
  the lifespan raised ``missing ['ENDPOINT_NAME']`` while all five PG* vars were
  present, which is also proof the other five do arrive.

  Because nothing injects ENDPOINT_NAME, app.yaml is its only source rather than a
  competing second one — the objection that applies to restating an *injected*
  value does not apply to it.

  All six names are read verbatim — never copied into PG_HOST-style aliases, never
  defaulted over, and never reconstructed from the SDK. There is deliberately no
  discovery fallback: anything that fills in a missing host is something that can
  disagree with the attached resource without saying so.

* **The credential API is the Autoscaling one.** ``databricks-sdk`` defines
  ``generate_database_credential`` twice, on two different services, returning two
  different classes that happen to share a name::

      w.postgres.generate_database_credential(endpoint=...)           # Autoscaling  <- this one
      w.database.generate_database_credential(instance_names=[...])   # instances

  We are projects/branches/endpoints, so it is ``w.postgres``. Its credential
  carries ``expire_time`` (a protobuf Timestamp); the *other* class carries
  ``expiration_time`` (an ISO string). Reaching for the wrong attribute fails at
  runtime inside the connect hook, roughly an hour after a green deploy.

  There is deliberately no fallback between the two. They address different
  products with different signatures, so picking whichever exists would connect
  to the wrong database rather than fail — which is worse than the AttributeError
  it would be papering over. ``assert_sdk_capabilities()`` below turns that
  AttributeError into a startup error that names the installed version instead.

Verified against databricks-sdk 0.127.0, which requirements.txt pins exactly::

    generate_database_credential(endpoint: str, *, claims=None, expire_time=None,
                                 group_name=None, ttl=None) -> DatabaseCredential
    DatabaseCredential(expire_time, token)
"""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

from databricks.sdk import WorkspaceClient

# All six are required. The five PG* names are injected by the attached Lakebase
# project resource; ENDPOINT_NAME is not, and comes from app.yaml. Named
# REQUIRED_VARS rather than INJECTED_VARS because that distinction is exactly what
# the old name got wrong, and getting it wrong cost a deploy.
REQUIRED_VARS = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGSSLMODE", "ENDPOINT_NAME")


def sdk_version() -> str:
    """The databricks-sdk version pip actually resolved in this container.

    Read from the installed distribution rather than a module attribute, because
    that is what pip decided; the attribute is what the package says about itself.
    They agree in a healthy install, and where they disagree the disagreement is
    itself the bug.
    """
    try:
        return _dist_version("databricks-sdk")
    except PackageNotFoundError:  # importable, but not as an installed dist
        try:
            from databricks.sdk.version import __version__

            return f"{__version__} (no installed distribution)"
        except ImportError:
            return "unknown"


def assert_sdk_capabilities() -> None:
    """Fail at startup if the SDK cannot mint Autoscaling credentials.

    Without this, an SDK missing ``postgres`` surfaces as an AttributeError raised
    from ``mint_password`` four frames inside SQLAlchemy's pool, naming neither the
    version installed nor what it has instead. That is precisely how
    ``databricks-sdk>=0.30`` reached production.

    Checked against the *class*, never an instance: ``WorkspaceClient.postgres`` is
    a property descriptor, so this needs no credentials and makes no network call.
    A check that can also fail for auth reasons cannot reliably report a version
    mismatch — it would just report the wrong cause.
    """
    version = sdk_version()

    if not hasattr(WorkspaceClient, "postgres"):
        # dir() has ~138 public names here; all of them would bury the one that
        # matters. The neighbours worth seeing are the database-shaped ones.
        related = sorted(
            a
            for a in dir(WorkspaceClient)
            if not a.startswith("_") and ("postgres" in a or "database" in a)
        )
        raise RuntimeError(
            f"databricks-sdk {version} has no WorkspaceClient.postgres; Lakebase "
            "Autoscaling credential minting requires it. Database-related attributes "
            f"present: {related}. There is deliberately no fallback to w.database: "
            "that is the Lakebase *instances* API, taking instance_names rather than "
            "an endpoint, and using it would connect to a different product instead "
            "of failing. Pin databricks-sdk==0.127.0 in requirements.txt and redeploy."
        )

    try:
        from databricks.sdk.service.postgres import PostgresAPI
    except ImportError as exc:
        raise RuntimeError(
            f"databricks-sdk {version}: WorkspaceClient.postgres exists but "
            f"databricks.sdk.service.postgres could not be imported ({exc}). The "
            "credential API cannot be called, and guessing at a moved module path "
            "would be a guess about which product answers. Pin "
            "databricks-sdk==0.127.0 in requirements.txt and redeploy."
        ) from exc

    params = list(inspect.signature(PostgresAPI.generate_database_credential).parameters)
    if "endpoint" not in params:
        raise RuntimeError(
            f"databricks-sdk {version}: postgres.generate_database_credential takes "
            f"{params}, with no 'endpoint' parameter. Autoscaling projects are "
            "addressed by endpoint; 'instance_names' would mean this is the instances "
            "API under a familiar name. Calling it anyway would mint a credential for "
            "something other than the attached Lakebase project. Pin "
            "databricks-sdk==0.127.0 in requirements.txt and redeploy."
        )


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
    """Read connection details from the environment.

    Raises if any variable is missing. In a deployed App all six are present and
    this is a pure environment read; to run migrations from a workstation, export
    all six — the five PG* values from the attached resource, and ENDPOINT_NAME
    matching what app.yaml sets.
    """
    missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        # The two halves have different causes and different fixes, so name the
        # one that applies rather than leaving the reader to work it out. A deploy
        # was lost to exactly that ambiguity: ENDPOINT_NAME was dropped from
        # app.yaml on the belief the resource would supply it, and it does not.
        causes = []
        if [name for name in missing if name != "ENDPOINT_NAME"]:
            causes.append(
                "The PG* names are injected by the attached Lakebase project "
                "resource, so a missing one means it is not attached."
            )
        if "ENDPOINT_NAME" in missing:
            causes.append(
                "ENDPOINT_NAME is NOT injected by the resource — app.yaml sets "
                "it, so it is missing or empty there."
            )
        raise RuntimeError(
            f"Lakebase environment is incomplete; missing {missing}. "
            + " ".join(causes)
            + " There is no fallback and nothing is reconstructed here, because a "
            "value invented at this point could disagree with the real endpoint "
            "without any error. To run migrations locally, export all of: "
            f"{', '.join(REQUIRED_VARS)}"
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
