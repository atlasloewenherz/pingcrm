# PingCRM

**Open-source personal networking CRM — AI-powered, self-hostable.**

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/sneg55/pingcrm)](https://github.com/sneg55/pingcrm/stargazers)
[![Build](https://github.com/sneg55/pingcrm/actions/workflows/deploy.yml/badge.svg)](https://github.com/sneg55/pingcrm/actions/workflows/deploy.yml)

Auto-syncs Gmail, Telegram, Twitter/X, LinkedIn, and WhatsApp. Detects life events. Drafts contextual follow-ups with AI. Tells you who to reach out to and why.

**[Docs](https://docs.pingcrm.xyz/)** · **[Setup Guide](https://docs.pingcrm.xyz/setup)** · **[Hosted Waitlist](https://pingcrm.xyz)**

---

## Why PingCRM?

| | PingCRM | Monica | Dex |
|---|---|---|---|
| Price | Free (self-hosted) | Free / $9/mo | Free tier / $12/mo |
| AI message drafting | ✅ | ❌ | ❌ |
| Gmail sync | ✅ threads | ❌ | ✅ contacts only |
| Telegram sync | ✅ | ❌ | ❌ |
| Twitter/X sync | ✅ DMs + mentions | ❌ | Import only |
| WhatsApp sync | ✅ QR pairing | ❌ | ❌ |
| LinkedIn sync | ✅ Chrome extension | ❌ | ✅ |
| Life event detection | ✅ multi-source | Manual | Job changes only |
| Self-hostable | ✅ | ✅ | ❌ |
| Open source | ✅ AGPL-3.0 | ✅ AGPL-3.0 | ❌ |

## What it does

- **Unified timeline** — every email, DM, mention, and call in one contact view
- **Relationship scoring** — 0–10 score surfaces who's going cold
- **AI suggestions** — drafts contextual follow-ups, never sends automatically
- **Life event detection** — new jobs, birthdays, bio changes across platforms
- **Identity resolution** — merges the same person across Gmail, LinkedIn, Telegram, etc.
- **MCP server** — query your CRM from Claude Desktop, Cursor, and other MCP clients

See the [feature docs](https://docs.pingcrm.xyz/features/dashboard) for screenshots and details.

---

## Get it running

### Option 1 — One-click deploy

| Platform | Deploy |
|---|---|
| **Railway** | [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/sneg55/pingcrm) |
| **Render** | [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/sneg55/pingcrm) |
| **DigitalOcean** | [![Deploy to DO](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/sneg55/pingcrm/tree/main) |
| **Fly.io** | `fly launch --from https://github.com/sneg55/pingcrm` |
| **Coolify** (self-hosted) | [Import as Docker Compose app](https://coolify.io/docs/applications/) |

After deploy, set `LLM_API_KEY` (or the legacy `ANTHROPIC_API_KEY`) and any OAuth credentials for integrations you want. [Environment reference →](https://docs.pingcrm.xyz/setup#environment-variables)

### Option 2 — Have an AI agent deploy it

Point Claude Code, Cursor, Codex, or any coding agent at [`AGENT_SETUP.md`](AGENT_SETUP.md) and ask it to deploy PingCRM on your VPS. Twelve-phase runbook — DNS, TLS, secrets, OAuth, the works.

```
"Read AGENT_SETUP.md and set up PingCRM for me on my server."
```

### Option 3 — Run it yourself

```bash
git clone https://github.com/sneg55/pingcrm.git
cd pingcrm
cp backend/.env.example backend/.env  # edit backend/integration values
cp .env.docker.example .env           # edit POSTGRES_PASSWORD and SECRET_KEY
docker compose up -d
```

Full walk-through with integration setup: **[docs.pingcrm.xyz/setup](https://docs.pingcrm.xyz/setup)**

### Configuring the LLM provider

AI features need one LLM provider. Anthropic is the default:

```env
LLM_API_KEY=your_anthropic_key
# or the legacy name, still honoured for Anthropic:
# ANTHROPIC_API_KEY=your_anthropic_key
```

Any OpenAI-compatible endpoint (OpenAI, Ollama, vLLM, ...) works by pointing
`LLM_BASE_URL` at it and prefixing both model IDs:

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=
LLM_MODEL_DRAFT=ollama/llama3
LLM_MODEL_FAST=ollama/llama3
LLM_ALLOW_EMPTY_KEY=true
```

The provider is selected from the model prefix — `anthropic/`, `openai/`,
`ollama/`, or `vllm/` — rather than a separate provider flag, so the model ID
is the single source of truth and a typo fails at startup instead of silently
routing to the wrong backend. `LLM_ALLOW_EMPTY_KEY=true` exists only for
self-hosted servers that accept no key (localhost or a trusted LAN); do not
enable it for a remote endpoint that requires authentication.

`LLM_MAX_CONCURRENCY` defaults to `5` and is shared by every service using the
same provider config. To match prior peak concurrency, set
`LLM_MAX_CONCURRENCY=10`.

### Staying up to date

PingCRM checks GitHub for new releases and shows an in-app banner when one
is available. See [Update Notifications](docs/docs/operations/updates.md)
for details and opt-out.

---

## Stack

**Backend:** FastAPI · PostgreSQL · Redis · Celery · Anthropic (default) or any OpenAI-compatible LLM
**Frontend:** Next.js · React · Tailwind
**Deploy:** Docker Compose · Caddy · GitHub Actions

[Architecture overview →](https://docs.pingcrm.xyz/architecture)

---

## Contributing

Contributions welcome — bugs, features, integrations, docs.

- [Contributing guide](CONTRIBUTING.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Open issues](https://github.com/sneg55/pingcrm/issues)

## License

[AGPL-3.0](LICENSE) — free to use, modify, self-host. Network use requires source disclosure.
