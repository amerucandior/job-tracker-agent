# Job Tracker Agent

An automated background agent for Linux that ingests job application emails across Gmail and Outlook, extracts hiring status changes using structured LLM outputs, and synchronizes a structured Notion job board with in-page timeline callouts.

---

## Architecture Overview

```text
[Gmail & Outlook]
       │ (OAuth2 Localhost Loopback / Headless Paste)
       ▼
[systemd --user Timer] (Every 30m, Python 3.13 via uv)
       │
       ├─► SQLite Checkpoint Store (~/.config/job-tracker/sync.db)
       │     └─► Idempotent message deduplication and thread mapping
       │
       ├─► Heuristic Pre-Filter (ATS domains + recruiter keywords)
       │     └─► Drops non-hiring email before model invocation
       │
       ├─► LLM Extraction (Pydantic schema; Cloud API / local Ollama fallback)
       │     └─► Thread-first matching with (Company, Role) fallback
       │
       ├─► Notion Job Board Sync (Auto-provisioned or mapped database)
       │     ├─► Properties: Company, Role, Stage, Review Flag, Last Activity
       │     └─► Body: Collapsible Timeline Callout with summary & action items
       │
       └─► Desktop Alert (notify-send on stage transition or review flag)
```

---

## Quickstart

### 1. Install & Setup Environment

The project is built with Python 3.13 managed via `uv`:

```bash
cd /home/ian/code/job-tracker-agent
uv sync
```

### 2. Configure Notion Board

Run the setup command to automatically provision the standardized Notion database under a parent page:

```bash
uv run job-tracker setup-notion --api-key <NOTION_API_KEY> --parent-page <PARENT_PAGE_ID>
```

Or connect an existing database:

```bash
uv run job-tracker setup-notion --api-key <NOTION_API_KEY> --database-id <DATABASE_ID>
```

### 3. Authenticate Email Accounts

#### Gmail
Place your Google Cloud OAuth client secret JSON at `~/.config/job-tracker/gmail_client_secret.json` or pass it explicitly:

```bash
uv run job-tracker auth gmail --secret-file /path/to/client_secret.json
```

#### Outlook / Microsoft 365
Authenticate with Microsoft Graph:

```bash
uv run job-tracker auth outlook
```

### 4. Run Manual Sync / Test Run

Preview what the agent finds without writing to Notion:

```bash
uv run job-tracker sync --dry-run
```

Run a real sync with a 14-day backfill:

```bash
uv run job-tracker sync --backfill-days 14
```

### 5. Enable Background Service (Fedora / Linux)

Install and activate the native `systemd --user` timer to poll every 30 minutes:

```bash
# Generate and install service units
uv run job-tracker service install --interval 30

# Enable and start the timer
uv run job-tracker service enable

# Check timer status
uv run job-tracker service status

# Follow logs in journalctl
uv run job-tracker service logs -n 50
```

---

## Configuration

Settings are stored at `~/.config/job-tracker/config.toml` adhering to the XDG specification:

```toml
[notion]
api_key = "secret_..."
database_id = "..."
parent_page_id = "..."

[llm]
provider = "gemini"               # gemini | openai | anthropic | ollama
model_name = "gemini-2.5-flash"   # or llama3.1 for ollama
api_key = "..."                   # Optional if set in GEMINI_API_KEY environment variable

[sync]
backfill_days = 14
polling_interval_minutes = 30
desktop_alerts = true
```

Tokens and OAuth credentials are saved securely in `~/.config/job-tracker/tokens.json` with strict `0600` permissions.

---

## Verification & Testing

Run the test suite using `pytest`:

```bash
uv run pytest
```
