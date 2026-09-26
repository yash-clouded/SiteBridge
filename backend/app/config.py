"""SiteBridge backend configuration (env-overridable, see .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SiteBridge"
    environment: str = "development"

    # PostgreSQL (+ pgvector from docker-compose; extension is enabled in Phase 5)
    database_url: str = "postgresql+psycopg://sitebridge:sitebridge@localhost:5432/sitebridge"

    # CORS for the Next.js dev server
    # Allowed browser origin(s), comma-separated. Local dev: the Next.js app
    # (3000) and the static HTML portal (8080); production: the Vercel domain.
    frontend_origin: str = "http://localhost:3000,http://localhost:8080,http://127.0.0.1:8080"

    # JWT auth (Phase 2) — role travels as a token claim
    jwt_secret: str = "dev-only-change-me-replace-in-prod-0123456789"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    # --- Phase 4: LLM extraction (OpenAI-compatible chat completions) -------
    # Any OpenAI-compatible server works (OpenAI, Azure, vLLM, Ollama, ...).
    # With no API key and the default OpenAI base URL the extractor is
    # DISABLED: nothing is guessed, no event is created.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 60.0
    llm_json_mode: bool = True
    llm_temperature: float = 0.0
    # Ask for the structured event as soon as a report lands (Phase 3 -> 4).
    auto_extract_on_intake: bool = True

    # --- Phase 5: embeddings ------------------------------------------------
    # "auto"  -> OpenAI embeddings when an API key is configured, otherwise the
    #            deterministic local provider (same pgvector tables, offline demo).
    # "openai" / "local" force a provider.
    embedding_provider: str = "auto"
    embedding_api_key: str = ""  # falls back to llm_api_key
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = ""  # falls back to llm_base_url
    # Vector width — must match the provider. Changing it requires recreating
    # the *_embeddings tables (docker compose down -v && uv run python seed.py).
    embedding_dim: int = 1536
    # Send `input_type` with every embedding call: "passage" when indexing,
    # "query" when embedding an event. Required by NVIDIA's E5/Nemotron
    # embedding models (nvidia/nemotron-3-embed-1b); harmless to OpenAI's
    # text-embedding-3-* (they ignore unknown fields), so leave it on for
    # those providers too if you prefer one switch.
    embedding_input_type: bool = False

    # --- Phase 5/7: retrieval ------------------------------------------------
    retrieval_top_k: int = 5

    # --- Phase 7: confidence -------------------------------------------------
    # final = retrieval_weight * retrieval_score + rule_weight * rule_score
    # `retrieval_score` is the Phase 5 cosine+KG score; `rule_score` is the
    # share of DECIDABLE Phase 6 rules that passed (unknown is excluded, so
    # missing data can neither help nor hurt). When no rule is decidable the
    # weights renormalise onto retrieval alone.
    confidence_retrieval_weight: float = 0.6
    confidence_rule_weight: float = 0.4
    # Bands drive the review queue: high/medium stay PENDING, low is flagged
    # NEEDS_MANUAL for a human to map by hand.
    confidence_high: float = 0.75
    confidence_medium: float = 0.5

    # --- Phase 11: fallbacks -------------------------------------------------
    # LLM ladder: LLM_BASE_URL -> LLM_FALLBACK_* -> heuristic extraction.
    # The fallback endpoint is tried only when the primary FAILS (timeout,
    # 4xx/5xx, unusable body) — never instead of it while it is healthy.
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""
    # What happens when NO endpoint answers:
    #   "heuristic" -> deterministic pattern extraction (no invention: a value
    #                  is read only when the report states it, else null)
    #   "off"       -> the report stays disabled/failed and no event is written
    extraction_fallback: str = "heuristic"
    # Embeddings: when the remote provider fails, re-embed with the local
    # provider ONLY if this project's index is still local. Two vector spaces
    # are never mixed — a wrong similarity score is worse than a clear error.
    embedding_fallback_local: bool = True

    # --- Multilingual intake (Sarvam) ---------------------------------------
    # A report can arrive in any supported Indian language. The text is
    # DETECTED and TRANSLATED to English before extraction, so the LLM prompt,
    # the knowledge-graph rules and the review queue all read one language —
    # while `raw_text` stays the verbatim evidence it always was.
    # No key (or a failed call) never blocks a submission: the report is
    # extracted as submitted and the translation is recorded as failed.
    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    # sarvam-translate:v1 -> all 22 scheduled languages, formal, 2000 chars
    # mayura:v1          -> 11 languages, `auto` detection, 1000 chars
    sarvam_translate_model: str = "sarvam-translate:v1"
    sarvam_target_language: str = "en-IN"
    translate_on_intake: bool = True
    translate_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
