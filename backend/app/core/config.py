from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/pingcrm"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _ensure_asyncpg_driver(cls, v: str) -> str:
        # Managed Postgres providers (Render, Railway, DO, Heroku) emit
        # postgres:// or postgresql:// URLs; SQLAlchemy's async engine needs
        # the +asyncpg driver tag.
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = "postgresql://" + v[len("postgres://"):]
            if v.startswith("postgresql://") and "+asyncpg" not in v:
                v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ENVIRONMENT: str = "development"  # Set to "production" in production deployments
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # PingCRM is single-player: there is no reason for the public internet to be
    # able to create accounts. Defaults to off so a deployment is closed even if
    # nobody remembers to plumb the env var through docker-compose.prod.yml.
    ALLOW_REGISTRATION: bool = False

    # Fixed-window throttles on the unauthenticated auth endpoints, keyed by client IP.
    AUTH_RATE_LIMIT_ENABLED: bool = True
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 10
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 900  # 15 minutes
    REGISTER_RATE_LIMIT_ATTEMPTS: int = 5
    REGISTER_RATE_LIMIT_WINDOW_SECONDS: int = 3600  # 1 hour

    # Number of reverse proxies between the internet and this app. Production is
    # a single Caddy container, so 1. Client IPs are read this many hops from the
    # *right* of X-Forwarded-For; anything further left is caller-supplied and
    # must never be trusted for throttling. Raise this only if you add proxies
    # (e.g. Cloudflare in front of Caddy would make it 2).
    TRUSTED_PROXY_HOPS: int = 1

    # Per-user throttle on endpoints that call the Anthropic API, so a stolen
    # token cannot run up an unbounded bill.
    LLM_RATE_LIMIT_ENABLED: bool = True
    LLM_RATE_LIMIT_ATTEMPTS: int = 30
    LLM_RATE_LIMIT_WINDOW_SECONDS: int = 3600  # 1 hour

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:3000/auth/google/callback"

    TWITTER_API_KEY: str = ""
    TWITTER_API_SECRET: str = ""
    TWITTER_CLIENT_ID: str = ""
    TWITTER_CLIENT_SECRET: str = ""
    TWITTER_REDIRECT_URI: str = "http://localhost:3000/auth/twitter/callback"

    ANTHROPIC_API_KEY: str = ""

    # LLM provider abstraction. The provider is derived from the model string's
    # prefix (anthropic/, openai/, ollama/, vllm/) rather than a separate
    # LLM_PROVIDER flag that could drift out of sync with it.
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL_DRAFT: str = "anthropic/claude-sonnet-4-6"
    LLM_MODEL_FAST: str = "anthropic/claude-haiku-4-5-20251001"
    # "none" | "json_object" | "json_schema". Anthropic ignores this — its
    # /v1/messages endpoint has no response_format parameter.
    LLM_STRUCTURED_OUTPUT: str = "none"
    LLM_TIMEOUT: float = 30.0
    # Total attempts, not retries after the first try: LLM_MAX_RETRIES=3 means
    # at most 3 calls (2 retries), matching complete_with_retry's max_attempts.
    LLM_MAX_RETRIES: int = 3
    # Per-call-site timeout overrides. Each defaults to the value the service used
    # before migration — taxonomy/tag-assignment calls can involve larger batches
    # and have historically used a longer timeout than the other services.
    # LLM_TIMEOUT (above) remains the floor used only if a caller passes
    # timeout=None; every current call site passes one of these explicitly.
    LLM_TIMEOUT_BIO_EXTRACTOR: float = 30.0
    LLM_TIMEOUT_EVENT_CLASSIFIER: float = 30.0
    LLM_TIMEOUT_TAXONOMY: float = 60.0
    LLM_TIMEOUT_TAG_ASSIGNMENT: float = 60.0
    LLM_TIMEOUT_MESSAGE_COMPOSER: float = 30.0
    LLM_TIMEOUT_MEETING_PREP: float = 30.0
    # Only for self-hosted, no-auth OpenAI-compatible servers (local Ollama,
    # vLLM on the LAN). Not a general escape hatch for remote endpoints.
    LLM_ALLOW_EMPTY_KEY: bool = False
    # Owned per adapter instance, shared by every service using the same
    # provider config. Set to 10 to match the previous combined peak across
    # event_classifier + auto_tagger.
    LLM_MAX_CONCURRENCY: int = 5

    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""

    TWITTER_BEARER_TOKEN: str = ""

    APOLLO_API_KEY: str = ""

    MAPBOX_SECRET_TOKEN: str = ""  # server-side geocoding
    MAPBOX_PUBLIC_TOKEN: str = ""  # surfaced to browser for map tiles

    ENCRYPTION_KEY: str = ""

    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    CHROME_EXTENSION_ID: str = ""

    # Public hostname of this instance (e.g. "crm.example.com"), no scheme.
    # Used to tell the Chrome extension where to reach the backend when
    # behind a reverse proxy -- request.base_url reports whatever internal
    # hostname the proxy actually connected on (e.g. the Docker Compose
    # service name), not the public one. Falls back to request.base_url when
    # unset, which is correct for unproxied local/dev setups.
    DOMAIN: str = ""

    FRONTEND_URL: str = "http://localhost:3000"

    WHATSAPP_SIDECAR_URL: str = "http://localhost:3001"
    WHATSAPP_WEBHOOK_SECRET: str = ""

    # env_ignore_empty: an empty environment variable means "not configured",
    # not "the empty value". Docker Compose writes every `VAR: ${VAR:-}` entry as
    # an empty string rather than omitting it, so any optional credential the
    # operator left blank arrives as "". Without this, blank non-string settings
    # (e.g. TELEGRAM_API_ID) fail validation and crash startup instead of falling
    # back to their defaults.
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)


settings = Settings()
