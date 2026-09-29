"""Environment-validated settings. Fails fast rather than booting insecurely."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

PLACEHOLDER_SECRETS = {
    "",
    "change-me",
    "changeme",
    "secret",
    "dev-secret-not-for-production",
}


class AppEnv(StrEnum):
    dev = "dev"
    test = "test"
    prod = "prod"


class LabelSource(StrEnum):
    """Which label set the tracer is allowed to read (D019).

    ``reviewed_sets`` is the import-then-review pipeline's own output.
    ``synthetic_fixture`` is ``data/anchors.csv``, which is fictional and must
    never serve a live trace.
    """

    reviewed_sets = "reviewed_sets"
    synthetic_fixture = "synthetic_fixture"


class DataMode(StrEnum):
    """Declared provenance of every observation the process produces (D009)."""

    LIVE = "LIVE"
    RECORDED_PUBLIC = "RECORDED_PUBLIC"
    SYNTHETIC = "SYNTHETIC"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CFA_", extra="ignore")

    app_env: AppEnv = AppEnv.dev
    data_mode: DataMode = DataMode.SYNTHETIC

    secret_key: str = "dev-secret-not-for-production"  # noqa: S105 - dev default, rejected outside dev
    session_cookie: str = "cfa_session"
    session_max_age_seconds: int = 60 * 60 * 8

    database_url: str = "sqlite+pysqlite:///../var/cfa.db"
    #: Reserved for upstream experiments. Unified v2 uses a database-leased
    #: durable queue; Redis is not required by operations_worker.py.
    redis_url: str | None = None

    engine_version: str = "0.1.0"
    label_set_version: str = "0"
    parser_version: str = "0.1.0"

    #: Fixed upper bound of every analysis. Nothing after this instant is read.
    analysis_cutoff: dt.datetime | None = None

    # Budgets are configuration targets, not measured performance (PRD section 8).
    budget_max_hops: int = 8
    budget_max_events: int = 5_000
    budget_max_provider_requests: int = 400
    budget_wall_clock_seconds: int = 300

    #: Monitoring (D029). A new watch re-reads this much history behind its
    #: checkpoint on every poll; it must exceed the provider's indexing and
    #: solidification lag, which has not been measured.
    monitor_overlap_seconds: int = Field(default=600, ge=0)
    #: Pages one poll may fetch before it stops and reports ``truncated``.
    monitor_max_pages: int = Field(default=20, ge=1)

    #: Left unset, the source follows the data mode: the synthetic fixture set
    #: under SYNTHETIC, the reviewed sets otherwise. Setting it explicitly is how
    #: a test or a recorded replay reads reviewed labels without being LIVE.
    label_source: LabelSource | None = None
    #: Directory holding verified_anchors.csv / deposit_candidates.csv.
    label_dir: str | None = None

    tron_api_base: str = "https://api.trongrid.io"
    tron_api_key: str | None = Field(default=None, repr=False)

    #: A JSON-RPC endpoint for Ethereum Mainnet. May embed a provider API key in
    #: its path/query, so it is never logged, persisted, or included in a saved
    #: bundle -- only whether it is configured. Left unset, Ethereum LIVE
    #: acquisition is refused rather than falling back to a public endpoint we
    #: did not choose (D009-equivalent: refuse, never substitute silently).
    ethereum_rpc_url: str | None = Field(default=None, repr=False)
    #: A JSON-RPC endpoint for BNB Smart Chain Mainnet (chain id 56). Same
    #: handling as ``ethereum_rpc_url``, and fully independent of it: neither
    #: ever stands in for the other.
    bsc_rpc_url: str | None = Field(default=None, repr=False)
    #: A JSON-RPC endpoint for Base Mainnet (chain id 8453). Same handling as
    #: ``ethereum_rpc_url`` and ``bsc_rpc_url``, and fully independent of them:
    #: none ever stands in for another.
    base_rpc_url: str | None = Field(default=None, repr=False)

    #: Investigation decision router mode ('rules', 'shadow_clm').
    decision_router: str = "rules"
    #: Optional remote CLM endpoint URL (e.g. http://127.0.0.1:8700). Never hardcoded.
    clm_url: str | None = Field(default=None, repr=False)
    #: Model identifier requested from the CLM server.
    clm_model: str = "qwen3-8b"
    #: Request timeout for remote CLM ranking calls in seconds.
    clm_timeout_seconds: float = 2.0
    #: Optional bearer API key for authenticated CLM endpoints (never logged/serialized).
    clm_api_key: str | None = Field(default=None, repr=False)

    @property
    def clm_model_identifier(self) -> str:
        """Backward-compatible alias for clm_model."""
        return self.clm_model

    @field_validator("secret_key")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _reject_synthetic_labels_in_live(self) -> Settings:
        if self.data_mode is DataMode.LIVE and self.label_source is LabelSource.synthetic_fixture:
            raise ValueError(
                "CFA_DATA_MODE=LIVE with CFA_LABEL_SOURCE=synthetic_fixture: refusing to "
                "serve live traces from the fictional label set"
            )
        return self

    @model_validator(mode="after")
    def _reject_placeholder_secret_outside_dev(self) -> Settings:
        if self.app_env is not AppEnv.dev and self.secret_key in PLACEHOLDER_SECRETS:
            raise ValueError(
                "CFA_SECRET_KEY is a placeholder; refusing to start outside the dev environment"
            )
        if self.app_env is not AppEnv.dev and len(self.secret_key) < 32:
            raise ValueError("CFA_SECRET_KEY must be at least 32 characters outside dev")
        return self

    @model_validator(mode="after")
    def _validate_decision_router(self) -> Settings:
        valid_modes = {"rules", "shadow_clm", "clm_assisted"}
        if self.decision_router not in valid_modes:
            raise ValueError(
                f"CFA_DECISION_ROUTER={self.decision_router!r} is invalid; "
                f"must be one of {sorted(valid_modes)}"
            )
        if self.decision_router == "clm_assisted":
            raise ValueError(
                "CFA_DECISION_ROUTER=clm_assisted is disabled in this release; "
                "use 'rules' or 'shadow_clm'"
            )
        return self

    @property
    def effective_label_source(self) -> LabelSource:
        if self.label_source is not None:
            return self.label_source
        return (
            LabelSource.synthetic_fixture
            if self.data_mode is DataMode.SYNTHETIC
            else LabelSource.reviewed_sets
        )

    @property
    def label_directory(self) -> Path:
        return Path(self.label_dir) if self.label_dir else REPO_ROOT / "data"

    def evm_rpc_url(self, network_key: str) -> str | None:
        """The configured RPC URL for one EVM network, or ``None``.

        Looked up through the network's own ``rpc_setting`` in the EVM
        registry, so one network's URL can never serve another.
        """
        from app.adapters.evm import EVM_NETWORKS  # the registry imports this module

        config = EVM_NETWORKS.get(network_key)
        if config is None:
            raise ValueError(f"{network_key!r} is not a configured EVM network")
        value = getattr(self, config.rpc_setting)
        return value if isinstance(value, str) and value else None

    @property
    def cutoff(self) -> dt.datetime:
        return self.analysis_cutoff or dt.datetime.now(dt.UTC)


@lru_cache
def get_settings() -> Settings:
    return Settings()
