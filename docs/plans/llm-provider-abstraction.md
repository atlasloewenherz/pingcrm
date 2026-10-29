# LLM Provider Abstraction — Final Plan

> This file consolidates Round 2's §1 (architecture rationale) with the Round 3 amendment's §2–§7. It supersedes both `llm-provider-abstraction.md` (Round 1) and the amendment as standalone documents. Commit 0 on `feature/llm-provider-abstraction` should add this file at `docs/plans/llm-provider-abstraction.md` before commit 1 is written.

**Consolidation flags (per "flag, don't resolve silently"):**
- Round 2's §1 is a short "why" rationale (Protocol vs. ABC, two adapters vs. universal, prefix detection vs. `LLM_PROVIDER`, no LiteLLM) and does **not** itself describe `LLM_ALLOW_EMPTY_KEY`, the memoization key, or per-adapter semaphore sizing — those are "how" decisions and are covered in full, verbatim, in §3. Duplicating them into §1 would contradict the instruction to keep §1 under one page and not restate the debate. §1 below adds only the minimal fix of naming `validate_llm_config()` explicitly (it previously only pointed at "§3, Startup validation"); the other three checklist bullets are intentionally left to §3 rather than duplicated.
- The `anthropic==0.40.0` / `.type` question (flagged "not independently re-verified" in the amendment) **was verified in this session**: an isolated, dependency-free install of `anthropic==0.40.0` was inspected directly. `anthropic.types.content_block.ContentBlock = Union[TextBlock, ToolUseBlock]` discriminated by `.type`, and `TextBlock.type: Literal["text"]`. The pin already supports commit 3's `block.type == "text"` check — no version bump is needed. Commit 1's message, the commit table, and the risk table below are updated to reflect this resolved result instead of carrying the open question forward.

---

## 1. Architecture rationale

### Why a Protocol, not an ABC
The seam is a single async method signature. A `typing.Protocol` gives us structural subtyping: adapters conform by shape, not inheritance, so tests can pass any object with a `complete(...)` method without forcing a base-class dependency. We add an ABC only if shared state (e.g., a real connection pool) emerges; it does not today.

### Why two adapters
Anthropic and OpenAI-compatible APIs disagree on how system prompts and structured output are expressed:
- Anthropic: native `system=` parameter, response content is a list of typed blocks (`TextBlock`, `ThinkingBlock`, `ToolUseBlock`, ...) — read `.text` off the block whose `.type == "text"`. No `response_format` parameter exists; see §3.
- OpenAI-compatible (`/v1/chat/completions`): system prompt is `messages[0]` with `role="system"`, response is `choices[0].message.content`.

A single "universal" adapter would become an `if/elif` kitchen sink. Two thin adapters keep the translation logic explicit and testable.

### Why model-prefix provider detection
Supported prefixes: `anthropic/`, `openai/`, `ollama/`, `vllm/`. Deriving the provider from the model string (`model.split("/", 1)[0]`) keeps the single source of truth in the model ID. We intentionally avoid a separate `LLM_PROVIDER` runtime flag, which can drift from the model string.

**No fallback for an unrecognized prefix.** No code is deployed yet and there are no legacy unprefixed `.env` values to protect — a fallback-to-Anthropic path would only introduce a silent misrouting surprise (e.g. a typo'd `LLM_MODEL_DRAFT=llama3` silently talking to Claude instead of the configured Ollama Cloud endpoint). Instead, an unrecognized prefix is a fail-fast startup error, enforced by `validate_llm_config()` — see §3, "Startup validation."

### Why not LiteLLM
LiteLLM would add a heavy dependency and its own configuration model. The project only needs two API shapes; two thin adapters is cheaper, auditable, and avoids another external proxy.

---

## 2. Git Flow roadmap

> **Deviation from the original instruction, stated plainly:** the original instruction said to follow Git Flow (feature branch → release branch → tag → back-merge). This repo has never used a release branch, a back-merge, or a version tag for any feature, including larger ones (org dedup, WhatsApp integration) — every merge in `git log --merges` is feature/fix branch → `develop`/`main` directly. Below are both options; **recommendation: (b)**, for the reasons given. If the reviewer wants Git Flow honored literally, switch to (a) — the release/tag/back-merge mechanics are fully specified structurally below; only the specific commit messages would need to be filled in.

**Option (a) — Enforce Git Flow as instructed:** `feature/llm-provider-abstraction` → PRs 1–3 into `develop` → cut `release/llm-provider-abstraction` → merge to `main` with a `vX.Y.Z` tag → back-merge to `develop`. Honors the instruction literally. Cost: introduces a branch/tag/back-merge pattern this repo has never used, for one feature, that nothing else in the project will follow afterward — a one-off ceremony a future reader of `git log` will find unexplained.

**Option (b) — Match repo convention:** `feature/llm-provider-abstraction` → PRs 1–3 into `develop` → a normal PR merging `develop` into `main` when ready, optionally tagged. Cost: departs from the literal instruction.

**Recommendation: (b).** The repo's actual Git Flow — in the sense that matters operationally (long-lived `develop`, short-lived feature branches, `--no-ff` merges, no direct pushes to `main`) — is already followed by both options; the only piece option (a) adds is a release-branch-and-tag ritual that has zero precedent and no consumer (no changelog tooling, no multi-version support policy, nothing currently reads a `v*` tag except the unused `deploy.yml` trigger). Adding it for one feature creates an inconsistency the next contributor has to explain, not a safety improvement.

### Branches
- Start from: `develop`
- Feature branch: `feature/llm-provider-abstraction`

### PR groupings
| PR | Commits | Purpose |
|---|---|---|
| **PR 1** | 1–5 | Dependency bump; build the seam: protocol, error hierarchy, settings, test fakes/fixture, adapters, factory, startup validation (API **and** worker) |
| **PR 2** | 6–10 | Migrate the five services (message_composer before meeting_prep), updating their existing tests |
| **PR 3** | 11–15 | Contract/PII/eval tests, the eval CI gate, config docs, provider-neutral docs |

### Merge strategy
- Merge each PR to `develop` with `--no-ff`.
- After PR 3 is green on `develop`, open a normal PR merging `develop` into `main`.
- Tagging `main` with `vX.Y.Z` is optional, not required. (Switch to Option (a) above if the reviewer overrules this.)

### Commit table

| # | Commit message | Files touched | Outcome | Body |
|---|---|---|---|---|
| 1 | `chore(deps): add openai and verify anthropic pin supports typed content blocks` | `backend/requirements.txt` | Dependency present before first import | Adds `openai>=1,<2` for the OpenAI-compatible adapter. **Verified in this session** against the installed `anthropic==0.40.0` package: `anthropic.types.content_block.ContentBlock = Union[TextBlock, ToolUseBlock]` discriminated by `.type`, and `TextBlock.type: Literal["text"]` — the pin already supports commit 3's `block.type == "text"` check. No pin bump needed. No other dependency changes. |
| 2 | `feat(llm): add LLMClient protocol, LLMError hierarchy, full LLM_* settings, and test fakes` | `backend/app/services/llm.py`, `backend/app/core/config.py`, `backend/tests/fakes.py`, `backend/tests/conftest.py` | Interface, error contract, config, test seam | Adds `LLMClient` Protocol and status-code-based `LLMError.is_transient`. Adds the full settings block up front: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL_DRAFT`, `LLM_MODEL_FAST`, `LLM_STRUCTURED_OUTPUT`, `LLM_TIMEOUT`, `LLM_MAX_RETRIES`, `LLM_ALLOW_EMPTY_KEY=False`, `LLM_MAX_CONCURRENCY=5`. Includes `complete_with_retry`. Adds `backend/tests/fakes.py::FakeLLMClient`. Adds the `fake_llm_client` async fixture to the **existing** `backend/tests/conftest.py` (not a new file) — see §4. |
| 3 | `feat(llm): implement AnthropicAdapter` | `backend/app/services/llm.py` | Native Anthropic backend | Uses `anthropic.AsyncAnthropic`; `system=` as top-level kwarg; scans for the first `.type == "text"` content block. Ignores `response_format` entirely (no such Anthropic parameter). Resolves its API key per the order in §3 (`LLM_API_KEY`, else `ANTHROPIC_API_KEY` with a one-time warning). Wraps `anthropic.APIStatusError`/`asyncio.TimeoutError`, preserving `status_code`. `timeout=` passed per call. Owns `self._semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY)`. Strips `anthropic/`. |
| 4 | `feat(llm): implement OpenAICompatibleAdapter` | `backend/app/services/llm.py` | OpenAI-compatible backend | Uses `openai.AsyncOpenAI`; `role="system"` as `messages[0]`, raising `ValueError` if the caller already supplied one. Substitutes a placeholder key only when `LLM_ALLOW_EMPTY_KEY=true` and the key is empty; otherwise raises `ValueError` at construction. Caches a `response_format` rejection per model string on `self._no_structured_output: set[str]` — cache lives for the process lifetime; see §3's trade-off note. Owns its own semaphore. `timeout=` per call. Strips `openai/`, `ollama/`, `vllm/`. |
| 5 | `feat(llm): add get_llm_client factory, memoization, and startup validation in both API and worker processes` | `backend/app/services/llm.py`, `backend/app/main.py`, `backend/app/core/celery_app.py`, `backend/tests/test_llm_startup_validation.py` | Provider selection + fail-fast in every runtime | `get_llm_client(model)` memoized by `(adapter_kind, base_url, api_key)`. Adds `validate_llm_config()`, raising `RuntimeError` on an unrecognized `LLM_MODEL_DRAFT`/`LLM_MODEL_FAST` prefix. Called from `app/main.py`'s `lifespan()` **and** from a `celery.signals.worker_process_init` handler in `celery_app.py` — `auto_tagger`, `event_classifier`, and `bio_extractor` run in Celery workers, and `worker_ready` fires too late (after the worker starts accepting tasks); `worker_process_init` fires in each forked child before any task is dequeued. New test file covers both the `RuntimeError`-raising and passing cases for the signal handler directly. |
| 6 | `refactor(bio_extractor): use LLMClient instead of direct anthropic import` | `backend/app/services/bio_extractor.py`, `backend/tests/test_bio_extractor.py` | First migration | `get_llm_client(settings.LLM_MODEL_FAST).complete(...)`. **Model role: `LLM_MODEL_FAST`.** Test uses the `fake_llm_client` fixture from `backend/tests/conftest.py`; replaces `patch('anthropic.AsyncAnthropic')`. |
| 7 | `refactor(event_classifier): use LLMClient` | `backend/app/services/event_classifier.py`, `backend/tests/test_event_classifier.py` | Second migration | **Model role: `LLM_MODEL_DRAFT`.** Removes the module-level `_llm_semaphore`; concurrency now lives on the memoized adapter and is shared with every other service on the same provider config — `LLM_MAX_CONCURRENCY=5` is tighter than today's two independent `Semaphore(5)`s. **Operators who need to match prior peak concurrency (up to 10 concurrent Anthropic calls across `event_classifier` + `auto_tagger`) should set `LLM_MAX_CONCURRENCY=10`.** Test uses `fake_llm_client`; replaces `patch('anthropic.AsyncAnthropic')`. |
| 8 | `refactor(auto_tagger): use LLMClient` | `backend/app/services/auto_tagger.py`, `backend/tests/test_auto_tagger.py` | Third migration | **Model role: `LLM_MODEL_FAST`.** `assign_tags(client=...)` now accepts an `LLMClient`. Module-level `_llm_semaphore` removed for the same reason as commit 7. Test uses `fake_llm_client`; replaces `patch('anthropic.AsyncAnthropic')`. |
| 9 | `refactor(message_composer): use LLMClient` | `backend/app/services/message_composer.py`, `backend/tests/test_message_composer.py`, `backend/tests/test_message_composer_extended.py` | Fourth migration | Removes module-level `_call_anthropic_with_retry`. **Model role: `LLM_MODEL_DRAFT`.** Must land before commit 10, which depends on this one no longer exporting `_call_anthropic_with_retry`. Test uses `fake_llm_client`. |
| 10 | `refactor(meeting_prep): use LLMClient` | `backend/app/services/meeting_prep.py`, `backend/tests/test_meeting_prep.py` | Fifth migration | Removes the module-level `import anthropic` and the import of `_call_anthropic_with_retry` from `message_composer` — now buildable in isolation because commit 9 already removed that helper. **Model role: `LLM_MODEL_FAST`.** `test_meeting_prep_email.py`/`test_task_jobs_meeting_prep.py` confirmed to need no changes. Test uses `fake_llm_client`. |
| 11 | `test(llm): add contract tests for both adapters` | `backend/tests/test_llm_adapter_contract.py` | Protocol conformance | Full list in §4: `system` placement, no `response_format` to Anthropic, `is_transient` per status, `LLM_ALLOW_EMPTY_KEY` true/false, memoization identity, concurrency cap, structured-output rejection cache, `role="system"` conflict raises `ValueError`. |
| 12 | `test(llm): add transport-layer PII leak test` | `backend/tests/test_llm_pii_logging.py`, `backend/app/core/logging_config.py` | PII discipline | `RedactMessagesFilter` introduced here, attached to handlers, SDK debug loggers set to `WARNING`. |
| 13 | `test(llm): add golden eval harness and required CI gate` | `backend/tests/eval_llm_golden.py`, `backend/tests/fixtures/golden/*.json`, `.github/workflows/llm-eval.yml` | Quality regression, enforced | Single authoritative workflow (§4): path-filtered, fails (not skips) with no key, `/run-llm-eval` override scoped to `OWNER`/`MEMBER`/`COLLABORATOR`. |
| 14 | `docs: update env examples, compose files, and setup guide for the new LLM_* settings` | `README.md`, `docs/docs/setup.md`, `backend/.env.example`, `.env.docker.example`, `docker-compose.yml`, `docker-compose.prod.yml` | Self-hostable config | Updates (not creates) existing env/compose files. Documents `LLM_ALLOW_EMPTY_KEY` topologies and states: **"to match prior peak concurrency, set `LLM_MAX_CONCURRENCY=10`."** Manual verification required before merge: a real Ollama Cloud model ID format, tested live (no `:cloud`-suffix convention is asserted here — unverified). |
| 15 | `docs: make LLM-backend descriptions provider-neutral` | `docs/docs/architecture.md`, `docs/docs/intro.md`, `docs/docs/features/twitter.md`, `docs/docs/features/gmail.md`, `docs/docs/features/suggestions.md`, `docs/docs/features/contacts.md` | Honest self-hostable docs | Frontend excluded — its one "Claude" string refers to Claude Desktop as an MCP client, not the LLM backend. |

### Merge commit messages

**PR 1 merge (`develop`):**
```
feat(llm): merge adapter seam into develop

Adds the openai dependency, the LLMClient Protocol, AnthropicAdapter,
OpenAICompatibleAdapter, a memoized model-prefix-based factory, and
startup validation wired into both the FastAPI lifespan and the Celery
worker_process_init signal — a misconfigured LLM_MODEL_* now fails to
boot in every runtime that uses it, not just the API process.
```

**PR 2 merge (`develop`):**
```
refactor(services): migrate five LLM services to the new seam

Replaces direct anthropic imports in:
- bio_extractor (LLM_MODEL_FAST)
- event_classifier (LLM_MODEL_DRAFT)
- auto_tagger (LLM_MODEL_FAST)
- message_composer (LLM_MODEL_DRAFT)
- meeting_prep (LLM_MODEL_FAST)

message_composer migrates before meeting_prep, which depends on its
retry helper. Per-service Semaphore(5) in event_classifier/auto_tagger
is replaced by a per-adapter-instance semaphore sized by
LLM_MAX_CONCURRENCY (default 5, shared across services on the same
provider config — set to 10 to match prior combined peak concurrency).

Verify: `grep -r 'import anthropic' backend/app` returns only
`backend/app/services/llm.py`.

Rollback: `git revert -m 1 <merge-sha>` on develop; no database
migration in this PR.
```

**PR 3 merge (`develop`):**
```
test(llm): merge contract, PII, and eval tests into develop; make docs
provider-neutral

Adds adapter-boundary contract tests, a transport-layer PII logging
test, a golden eval harness with a required-on-touch CI gate scoped to
OWNER/MEMBER/COLLABORATOR for manual override, and updates setup/env
and feature docs that described the LLM backend as Claude-specific.
```

**`develop` → `main` merge:**
```
feat(llm): bring Anthropic and OpenAI-compatible adapter support to main

Merges the LLM provider abstraction seam from develop. Optionally tag as
vX.Y.Z if adopting the tag-triggered deploy path.
```

---

## 3. Technical decisions

### Empty-key handling: explicit flag, not hostname sniffing
`LLM_ALLOW_EMPTY_KEY: bool = False`. `OpenAICompatibleAdapter.__init__` substitutes a placeholder key only when the flag is `true` and `api_key == ""`; otherwise it raises `ValueError` at construction, naming `docs/docs/setup.md`. `openai.AsyncOpenAI` rejects empty keys (no SDK version cited — unverified).

### API key resolution order
Resolution order for `adapter_kind == "anthropic"`: `LLM_API_KEY` if non-empty; else `ANTHROPIC_API_KEY` with a one-time `logger.warning`; else `""`. For `adapter_kind == "openai_compatible"`: `LLM_API_KEY`; else `""` (subject to `LLM_ALLOW_EMPTY_KEY`). `ANTHROPIC_API_KEY` is never consulted for the OpenAI-compatible path.

### Structured-output flag
`AnthropicAdapter` ignores `LLM_STRUCTURED_OUTPUT` entirely — no `response_format` parameter exists on `/v1/messages`. On `OpenAICompatibleAdapter`, a rejection (typically a 400) is logged once and the model string is recorded in `self._no_structured_output: set[str]`; subsequent calls for that model skip attaching `response_format`. **This cache never invalidates for the life of the process.** If a local Ollama is upgraded mid-run to support `response_format`, the cache still says "no" until restart. Acceptable trade-off — the failure mode is one wasted round-trip per restart cycle, not a correctness issue. No TTL added.

### Unified error translation
`LLMError.is_transient` is `True` for `429` or any `≥500`, or a connection/timeout error with no status code — matching every service's current `{429, 500, 529}`-style behavior. `False` for every other 4xx.

### Adapter lifecycle (memoization)
`get_llm_client` memoized by `(adapter_kind, base_url, api_key)` under a module-level `asyncio.Lock`, so a single adapter instance (and its semaphore, and its rejection cache) serves every model sharing that config.

### Concurrency
`LLM_MAX_CONCURRENCY: int = 5`, owned per adapter instance. Because adapters are memoized by provider config, every service resolving to the same `(adapter_kind, base_url, api_key)` shares one semaphore — in the default Phase 1 config, all five services share one cap of 5, tighter than today's combined-up-to-10 across `event_classifier`+`auto_tagger`. Operators who need the old combined ceiling set `LLM_MAX_CONCURRENCY=10` (documented in commit 7 and commit 14).

### Startup validation (API and worker)
```python
SUPPORTED_PREFIXES = {"anthropic", "openai", "ollama", "vllm"}

def validate_llm_config() -> None:
    for name in ("LLM_MODEL_DRAFT", "LLM_MODEL_FAST"):
        model = getattr(settings, name)
        prefix = model.split("/", 1)[0] if "/" in model else ""
        if prefix not in SUPPORTED_PREFIXES:
            raise RuntimeError(
                f"{name}={model!r} must begin with one of "
                f"{sorted(SUPPORTED_PREFIXES)}. See docs/docs/setup.md."
            )
```

Called from `app/main.py`:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_llm_config()
    ...
```

**And** from `app/core/celery_app.py`, because `auto_tagger`, `event_classifier`, and `bio_extractor` execute in Celery workers, not the API process — covering three of five services' primary runtime:
```python
from celery.signals import worker_process_init
from app.services.llm import validate_llm_config

@worker_process_init.connect
def _validate_llm_config_on_worker_start(**kwargs):
    validate_llm_config()
```

`worker_process_init` fires in each forked worker child **before** it starts consuming from the broker. `worker_ready` was considered and rejected: it fires after the worker has already connected and announced readiness, which is too late — a task could already be in flight by the time it runs.

### Timeout granularity
`timeout=` passed per call, never at client construction.

### System-prompt contract
`OpenAICompatibleAdapter.complete()` raises `ValueError` if `messages` already contains a `role="system"` entry.

---

## 4. Verification

### Test fixtures (`backend/tests/conftest.py`, new fixture added in commit 2)
`get_llm_client` is `async`, guarded by `asyncio.Lock`. A synchronous lambda monkeypatch (`lambda _: FakeLLMClient()`) returns a coroutine, not the fake, and the call site's `await` receives a coroutine object with no `.complete` — an `AttributeError` discovered mid-migration rather than up front. The fixture:

```python
@pytest.fixture
def fake_llm_client(monkeypatch):
    fake = FakeLLMClient()
    async def _get(_model: str) -> LLMClient:
        return fake
    monkeypatch.setattr("app.services.llm.get_llm_client", _get)
    return fake
```

`get_llm_client` is async-only by contract; if a future synchronous call path is ever needed, this fixture's return shape changes accordingly — not assumed here.

### Contract tests (`backend/tests/test_llm_adapter_contract.py`)
- `system=` placement for both adapters; `AnthropicAdapter` never sends `response_format`.
- `response_format` present/absent per `LLM_STRUCTURED_OUTPUT` on the OpenAI-compatible path.
- `LLM_ALLOW_EMPTY_KEY=true` + empty key + local `base_url` → constructs; `LLM_ALLOW_EMPTY_KEY=false` + empty key → raises `ValueError`.
- `LLMError.is_transient`: `True` for 429/500/502/503/529; `False` for 400/401/403/404/422.
- `get_llm_client` called twice with identical settings → same instance; changed `LLM_BASE_URL` → different instance.
- Concurrency: 6 concurrent calls against `LLM_MAX_CONCURRENCY=5` never exceed 5 in flight.
- Structured-output rejection cache: second call for a rejected model never attaches `response_format`.
- `OpenAICompatibleAdapter` raises `ValueError` on a pre-existing `role="system"` message.
- Both adapters satisfy structural `LLMClient` conformance.

### Startup validation tests (`backend/tests/test_llm_startup_validation.py`, added in commit 5)
- `validate_llm_config()` raises `RuntimeError` for an unrecognized/missing prefix; passes for every supported one.
- `_validate_llm_config_on_worker_start()` (the Celery signal handler), invoked directly: raises when `LLM_MODEL_DRAFT` is unprefixed (e.g. `"claude-sonnet-4-6"`); passes when both `LLM_MODEL_DRAFT` and `LLM_MODEL_FAST` carry a supported prefix.

### PII logging test
Installs `RedactMessagesFilter` on every handler in `setup_logging()`. Sets `anthropic.*` and `openai.*` SDK logger levels to `WARNING`. Creates a child logger, emits a record whose args contain real message content, asserts the handler output does not contain it.

### Golden eval harness and CI gate — single authoritative copy
```yaml
name: LLM golden eval

on:
  pull_request:
    paths:
      - "backend/app/services/llm.py"
      - "backend/app/core/config.py"
      - "backend/app/core/celery_app.py"
      - "backend/app/services/message_composer.py"
      - "backend/app/services/event_classifier.py"
      - "backend/app/services/auto_tagger.py"
      - "backend/app/services/bio_extractor.py"
      - "backend/app/services/meeting_prep.py"
  issue_comment:
    types: [created]

jobs:
  eval:
    if: >
      github.event_name == 'pull_request' ||
      (github.event_name == 'issue_comment' &&
       github.event.issue.pull_request != null &&
       contains(github.event.comment.body, '/run-llm-eval') &&
       contains(fromJSON('["OWNER","MEMBER","COLLABORATOR"]'), github.event.comment.author_association))
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event_name == 'issue_comment' && format('refs/pull/{0}/head', github.event.issue.number) || github.head_ref }}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r backend/requirements.txt -r backend/requirements-test.txt
      - name: Run golden eval
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          if [ -z "$ANTHROPIC_API_KEY" ] && [ "${{ github.event_name }}" = "pull_request" ]; then
            echo "::error::ANTHROPIC_API_KEY not configured — required for changes touching LLM code. A maintainer must comment /run-llm-eval once a key is available."
            exit 1
          fi
          cd backend && pytest -m eval tests/eval_llm_golden.py
```
`/run-llm-eval` is scoped to `OWNER`/`MEMBER`/`COLLABORATOR` — the run spends a paid API key, so arbitrary commenters on a public repo shouldn't be able to trigger it. Making the check block merges still requires a maintainer to mark it required in branch-protection settings (outside this PR's diff); the `issue_comment` re-run path should be smoke-tested against a real PR before being relied on.

### Regression guard
Existing service tests are updated in the same commits that change the services. Commits 6–10 use the `fake_llm_client` fixture rather than `patch('anthropic.AsyncAnthropic')`. `test_meeting_prep_email.py` and `test_task_jobs_meeting_prep.py` were audited and need no changes.

---

## 5. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Retry classification regresses from status-code to exception-type** | Permanent errors get retried `LLM_MAX_RETRIES` times. | `is_transient` tested against status code; contract test covers both cases. |
| **Concurrency cap removed during semaphore consolidation** | Unbounded concurrency returns. | Semaphore moves to the adapter instance, not deleted; concurrency contract test. |
| **`LLM_ALLOW_EMPTY_KEY=true` set against a real remote endpoint requiring auth** | Opaque 401 instead of a clear construction-time error. | Documented operator assertion; `docs/docs/setup.md` restricts guidance to self-hosted local/LAN servers. |
| **`LLM_ALLOW_EMPTY_KEY` left false against a genuine no-auth local server** | Construction raises instead of "just working." | Deliberate fail-fast; error names the setting and the doc. |
| **Structured-output rejection re-attempted on every call** | Wasted round-trips against a local model that always 400s. | Per-model rejection cache on the adapter instance; never invalidates for process lifetime — acceptable, since the only cost of staleness is one wasted call after a restart, not incorrect output. |
| **PII logging gaps** | SDK debug logs can echo message bodies. | `RedactMessagesFilter` on handlers; SDK loggers set to `WARNING`; transport-layer test. |
| **Model prefix drift / missing prefix** | Misconfigured `LLM_MODEL_*`. | **Fails at boot in both API and worker containers** — `validate_llm_config()` runs from `lifespan()` and from Celery's `worker_process_init`, so a worker never silently accepts tasks it can't execute. |
| **Auto-tagger client reuse leak** | Connection churn. | Memoization guarantees one adapter instance per config. |
| **Service-level exception handling changes** | Fallback logic regresses. | `LLMError` treated as LLM failure; existing fallback logic preserved. |
| **Non-text content block in Anthropic response** | Silent misread if thinking/tools are enabled later. | Adapter scans for `.type == "text"`, raises `LLMError` if absent. |
| **No existing CI enforcement path for the eval gate** | `llm-eval.yml` is new infrastructure; visibility ≠ enforcement. | Caveat stated in §4: branch-protection "required" setting is a separate manual step; `/run-llm-eval` path needs a live smoke test. |
| ~~`openai` dependency pin never verified against the installed `anthropic==0.40.0`'s content-block `.type` support~~ | — | **Resolved in this consolidation** (see top-of-file flag and commit 1): verified directly against an isolated install of `anthropic==0.40.0`. `.type` discrimination on `ContentBlock` is present; no pin bump needed. Kept here, struck through, so the resolution is visible rather than the row silently vanishing. |

---

## 6. Commit messages (verbatim, paste-ready)

### Commit 1
```
chore(deps): add openai and verify anthropic pin supports typed content blocks

Adds openai>=1,<2 for the OpenAI-compatible adapter. Verified against
the installed anthropic==0.40.0 package: ContentBlock is
Union[TextBlock, ToolUseBlock] discriminated by .type, and
TextBlock.type is Literal["text"] — the pin already supports the
block.type == "text" check used in commit 3. No pin bump needed. No
other dependency changes.
```

### Commit 2
```
feat(llm): add LLMClient protocol, LLMError hierarchy, full LLM_*
settings, and test fakes

Adds the LLMClient Protocol and LLMError, with is_transient based on
HTTP status code (429 or >=500), matching every service's current
transient_codes = {429, 500, 529} check. Adds the full settings block
up front: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_DRAFT, LLM_MODEL_FAST,
LLM_STRUCTURED_OUTPUT, LLM_TIMEOUT, LLM_MAX_RETRIES,
LLM_ALLOW_EMPTY_KEY (default False), LLM_MAX_CONCURRENCY (default 5)
— so later commits never forward-reference an undefined setting.
Includes complete_with_retry. Adds backend/tests/fakes.py::
FakeLLMClient and the fake_llm_client async fixture to the existing
backend/tests/conftest.py.
```

### Commit 3
```
feat(llm): implement AnthropicAdapter

Uses anthropic.AsyncAnthropic. Passes system as a top-level kwarg.
Scans response.content for the first block with type == "text";
raises LLMError if none is found. Ignores response_format entirely —
Anthropic's /v1/messages has no such parameter; structured output
here is prompt-based JSON instructions plus application-side schema
validation only. Resolves its API key as LLM_API_KEY, else
ANTHROPIC_API_KEY with a one-time warning, else empty. Wraps
anthropic.APIStatusError/asyncio.TimeoutError, preserving status_code
for is_transient. Passes timeout per call, not at client
construction. Owns asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY) as
an instance attribute. Strips the anthropic/ prefix.
```

### Commit 4
```
feat(llm): implement OpenAICompatibleAdapter

Uses openai.AsyncOpenAI with configurable base_url/api_key. Prepends
the system prompt as messages[0] with role="system"; raises
ValueError if the caller's messages already contains a role="system"
entry. Substitutes a placeholder key only when
LLM_ALLOW_EMPTY_KEY=true and the key is empty; otherwise raises
ValueError at construction, pointing to docs/docs/setup.md. On a
response_format rejection (typically 400), logs a warning once and
caches the model string in self._no_structured_output; later calls
for that model skip response_format. Owns its own
asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY). Passes timeout per
call. Strips openai/, ollama/, vllm/ prefixes.
```

### Commit 5
```
feat(llm): add get_llm_client factory, memoization, and startup
validation in both API and worker processes

get_llm_client(model) picks the adapter class by prefix and is
memoized by (adapter_kind, base_url, api_key) under a module-level
asyncio.Lock, so identical config returns the identical adapter
instance. Adds validate_llm_config(), raising RuntimeError when
LLM_MODEL_DRAFT or LLM_MODEL_FAST has a prefix outside {anthropic,
openai, ollama, vllm}. Calls it from app/main.py's lifespan() and
from a celery.signals.worker_process_init handler in celery_app.py —
auto_tagger, event_classifier, and bio_extractor run in Celery
workers, and worker_ready fires too late (after the worker starts
accepting tasks); worker_process_init fires in each forked child
before any task is dequeued. No fallback adapter for an unrecognized
prefix.
```

### Commit 6
```
refactor(bio_extractor): use LLMClient instead of direct anthropic
import

Replaces the AsyncAnthropic client and per-service retry with
get_llm_client(settings.LLM_MODEL_FAST).complete(...). Model role:
LLM_MODEL_FAST. Test uses the fake_llm_client fixture from
backend/tests/conftest.py, replacing
patch('anthropic.AsyncAnthropic').
```

### Commit 7
```
refactor(event_classifier): use LLMClient

Model role: LLM_MODEL_DRAFT. Removes the module-level _llm_semaphore
— concurrency now lives on the memoized adapter and is shared with
every other service on the same provider config.
LLM_MAX_CONCURRENCY=5 is tighter than today's two independent
Semaphore(5) instances; operators who need to match prior combined
peak concurrency (up to 10 concurrent Anthropic calls across
event_classifier + auto_tagger) should set LLM_MAX_CONCURRENCY=10.
Test uses fake_llm_client, replacing
patch('anthropic.AsyncAnthropic').
```

### Commit 8
```
refactor(auto_tagger): use LLMClient

Model role: LLM_MODEL_FAST. assign_tags(client=...) now accepts an
LLMClient instead of AsyncAnthropic. Module-level _llm_semaphore
removed for the same reason as event_classifier. Test uses
fake_llm_client, replacing patch('anthropic.AsyncAnthropic').
```

### Commit 9
```
refactor(message_composer): use LLMClient

Model role: LLM_MODEL_DRAFT. Removes the module-level
_call_anthropic_with_retry. Lands before meeting_prep, which depends
on this helper no longer existing. Test uses fake_llm_client.
```

### Commit 10
```
refactor(meeting_prep): use LLMClient

Removes the module-level `import anthropic` (the only service with
one) and the import of _call_anthropic_with_retry from
message_composer, buildable in isolation now that message_composer
no longer exports it. Model role: LLM_MODEL_FAST.
test_meeting_prep_email.py and test_task_jobs_meeting_prep.py need no
changes — neither touches the LLM client. Test uses fake_llm_client.
```

### Commit 11
```
test(llm): add contract tests for both adapters

Covers: system placement for both adapters; AnthropicAdapter never
sends response_format; is_transient true for 429/>=500, false for
other 4xx; LLM_ALLOW_EMPTY_KEY true/false construction behavior;
get_llm_client memoization identity across identical and differing
config; a concurrency test asserting at most LLM_MAX_CONCURRENCY
calls are in flight; the structured-output rejection cache skipping
response_format on the second call; OpenAICompatibleAdapter raising
ValueError on a pre-existing role="system" message; structural
LLMClient conformance for both adapters.
```

### Commit 12
```
test(llm): add transport-layer PII leak test

Introduces RedactMessagesFilter, attached to logging handlers (not
loggers) in setup_logging(), and sets anthropic.* / openai.* SDK
logger levels to WARNING. Asserts a child logger emitting real
message content does not leak it in handler output.
```

### Commit 13
```
test(llm): add golden eval harness and required CI gate

Fixtures under backend/tests/fixtures/golden/ cover all five tasks;
the harness runs both adapters through get_llm_client and checks
schema/keyword conformance. Adds .github/workflows/llm-eval.yml,
path-filtered to LLM-touching files: fails (does not skip) when no
API key is configured on a pull_request event, with an
issue_comment-triggered /run-llm-eval override scoped to
OWNER/MEMBER/COLLABORATOR.
```

### Commit 14
```
docs: update env examples, compose files, and setup guide for the new
LLM_* settings

Updates (does not create) backend/.env.example, .env.docker.example,
docker-compose.yml, docker-compose.prod.yml, README.md, and
docs/docs/setup.md, which already exist and already carry
ANTHROPIC_API_KEY. Adds LLM_BASE_URL, LLM_MODEL_DRAFT, LLM_MODEL_FAST,
LLM_ALLOW_EMPTY_KEY, and LLM_MAX_CONCURRENCY alongside it, documenting
the Compose-service-name / LAN-IP / cluster-DNS topologies
LLM_ALLOW_EMPTY_KEY is for, and noting that LLM_MAX_CONCURRENCY=10
matches the prior combined peak concurrency. Requires manual
verification of a real Ollama Cloud model ID format before merge —
no suffix convention is asserted here.
```

### Commit 15
```
docs: make LLM-backend descriptions provider-neutral

Rewords docs/docs/architecture.md, intro.md, and the
twitter/gmail/suggestions/contacts feature pages, which described
follow-up drafting, event classification, and bio extraction as
Claude-specific, to name "your configured LLM provider" while keeping
Anthropic as the documented default. Frontend excluded: its one
"Claude" string (account-tab.tsx) describes connecting Claude Desktop
as an MCP client to PingCRM's own MCP server, unrelated to the LLM
backend, and is left unchanged — as are the Claude Desktop/MCP-client
mentions in docs/docs/features/mcp.md and settings.md.
```

### PR 1 merge (`develop`)
```
feat(llm): merge adapter seam into develop

Adds the openai dependency, the LLMClient Protocol, AnthropicAdapter,
OpenAICompatibleAdapter, a memoized model-prefix-based factory, and
startup validation wired into both the FastAPI lifespan and the
Celery worker_process_init signal — a misconfigured LLM_MODEL_* now
fails to boot in every runtime that uses it, not just the API
process.
```

### PR 2 merge (`develop`)
```
refactor(services): migrate five LLM services to the new seam

Replaces direct anthropic imports in:
- bio_extractor (LLM_MODEL_FAST)
- event_classifier (LLM_MODEL_DRAFT)
- auto_tagger (LLM_MODEL_FAST)
- message_composer (LLM_MODEL_DRAFT)
- meeting_prep (LLM_MODEL_FAST)

message_composer migrates before meeting_prep, which depends on its
retry helper. Per-service Semaphore(5) in event_classifier/
auto_tagger is replaced by a per-adapter-instance semaphore sized by
LLM_MAX_CONCURRENCY (default 5, shared across services on the same
provider config — set to 10 to match prior combined peak
concurrency).

Verify: `grep -r 'import anthropic' backend/app` returns only
`backend/app/services/llm.py`.

Rollback: `git revert -m 1 <merge-sha>` on develop; no database
migration in this PR.
```

### PR 3 merge (`develop`)
```
test(llm): merge contract, PII, and eval tests into develop; make
docs provider-neutral

Adds adapter-boundary contract tests, a transport-layer PII logging
test, a golden eval harness with a required-on-touch CI gate scoped
to OWNER/MEMBER/COLLABORATOR for manual override, and updates
setup/env and feature docs that described the LLM backend as
Claude-specific.
```

### `develop` → `main` merge
```
feat(llm): bring Anthropic and OpenAI-compatible adapter support to
main

Merges the LLM provider abstraction seam from develop. Optionally tag
as vX.Y.Z if adopting the tag-triggered deploy path.
```

---

## 7. Pre-implementation checklist

- [x] ~~Commit 1 (`openai` + `anthropic` pin) merged to `develop`; `import openai` succeeds on a fresh container.~~ The `anthropic==0.40.0` / `.type` half of this was verified in this consolidation (see top-of-file flag); the `openai` install and merge itself is still a real step the implementer must do.
- [ ] `FakeLLMClient` (`backend/tests/fakes.py`) and the async `fake_llm_client` fixture (added to the **existing** `backend/tests/conftest.py`) exist and are importable from a service test.
- [ ] `validate_llm_config()` is wired into **both** `app/main.py`'s `lifespan()` **and** `app/core/celery_app.py`'s `worker_process_init` signal — confirm by killing a worker container with a deliberately bad `LLM_MODEL_DRAFT` and observing it fails to come up, not just the API.
- [ ] Git Flow vs. repo-convention decision in §2 has been read and either accepted (option b, as recommended) or explicitly overridden to option (a) by the reviewer.
- [ ] Commit ordering is buildable: message_composer (commit 9) lands before meeting_prep (commit 10); each commit passes `pytest` in isolation on the branch.
- [ ] `LLM_MAX_CONCURRENCY=10` operator note is present in both commit 7's body and `docs/docs/setup.md`.
- [ ] `_resolve_api_key` resolution order (§3) matches what commit 3 actually implements.
- [ ] `_no_structured_output` cache's no-invalidation trade-off is acknowledged in §3 and no TTL has been added.
- [ ] `llm-eval.yml` appears exactly once in the repo; the `author_association` scoping on `/run-llm-eval` is in place; someone has confirmed with a maintainer that branch protection will mark it required.
- [ ] Verbatim commit messages (§6) reflect the final 1–15 numbering — no commit in the actual implementation PR refers to itself by a number from an earlier draft of this plan.
