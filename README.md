# Job Tracker Agent

An autonomous AI agent for Linux that monitors job applications across Gmail and Outlook (Personal & Enterprise), parses hiring updates using structured LLM output (Gemini or local Ollama), and synchronizes an organized Notion board with in-page collapsible timeline callouts.

---

## Key Capabilities

- **Zero Memory Consumption at Rest**: Uses native Linux `systemd --user` timer and `Type=oneshot` service. Consumes 0 MB of RAM between scheduled runs; spins up on schedule, processes inboxes, and terminates.
- **Reboot Persistent**: Automatically resumes on system boot (`Persistent=true`). If your computer was powered off when a sync was scheduled, it catches up on boot.
- **Multi-Mailbox Ingestion**: Supports Google OAuth2 for Gmail and Microsoft Graph MSAL PKCE for Outlook / Microsoft 365 (including Personal Consumer Accounts `@outlook.com` / `@hotmail.com`).
- **Two-Stage Filtering**:
  - *Heuristic Pre-Filter*: Fast regex and ATS domain matching (`greenhouse.io`, `lever.co`, `ashbyhq.com`, `workday.com`, etc.) while filtering out developer noise (GitHub issues, CI alerts).
  - *LLM Extraction*: Extracts real hiring company, role title, stage, confidence, summary, and action items into a validated Pydantic model.
- **Rich Notion Board**: Updates application stage (`Applied`, `Screening`, `Interview`, `Offer`, `Rejected`, `Archived`), timestamps, and appends collapsible timeline blocks tracking every communication.
- **Local SQLite Sync Ledger**: Idempotent message deduplication and thread-to-Notion card mapping stored in `~/.config/job-tracker/sync.db`.
- **Desktop Notifications**: Dispatches native notifications via `notify-send` when status changes occur or manual review is needed.

---

## Architecture

```text
[Gmail & Outlook]
       │ (OAuth2 / MSAL PKCE flow)
       ▼
[systemd --user Timer] (Weekly or periodic, Python 3.13 via uv)
       │
       ├─► SQLite Checkpoint Store (~/.config/job-tracker/sync.db)
       │     └─► Idempotent message deduplication & thread mapping
       │
       ├─► Heuristic Pre-Filter (ATS domains + recruiting regexes)
       │     └─► Drops developer/newsletter noise before model call
       │
       ├─► LLM Extraction (Structured JSON via Gemini API or Ollama)
       │     └─► Validates company, role, stage, action items
       │
       ├─► Notion Job Board Sync (Standardized database)
       │     ├─► Properties: Company, Role, Stage, Review Flag, Last Activity
       │     └─► Page Body: Collapsible Timeline Callout with history
       │
       └─► Desktop Alert (notify-send on stage changes)
```

---

## Prerequisites

- **Linux** (Fedora, Ubuntu, Debian, Arch, etc.) with `systemd` and `notify-send`
- **Python 3.13+** managed via [uv](https://docs.astral.sh/uv/)

```bash
# Clone the repository
git clone https://github.com/amerucandior/job-tracker-agent.git
cd job-tracker-agent

# Install dependencies into virtual environment
uv sync
```

---

## Configuration & Setup Guide

All configuration files and tokens are stored in the user XDG configuration directory (`~/.config/job-tracker/`) with strict permissions (`0600`). Nothing sensitive is committed to the repository.

### 1. Notion Setup

1. Go to [Notion My Integrations](https://www.notion.so/profile/integrations) and click **New integration**.
   - Name: `Job Tracker`
   - Capabilities: Read, Update, and Insert content.
   - Copy the **Internal Integration Secret** (`ntn_...`).
2. Open or create a parent page in Notion where you want your Job Applications board to live.
3. Click the `...` menu in the top right of the Notion page -> **Connections** (or **Add connections**) -> Search for `Job Tracker` -> Click **Connect**.
4. Copy the page URL or Page ID from your browser address bar.
5. Run the provisioner command:

```bash
uv run job-tracker setup-notion --api-key "ntn_..." --parent-page "<PARENT_PAGE_ID_OR_URL>"
```

This creates a database with canonical properties (`Company`, `Role`, `Stage`, `Review Flag`, `Last Activity`, `Thread IDs`) and saves the database ID to your configuration.

---

### 2. Google Cloud Setup (Gmail)

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable the **Gmail API** under **APIs & Services** > **Library**.
3. Configure **OAuth consent screen**:
   - User Type: **External**
   - Publishing Status: **Testing**
   - Add your email under **Test users**.
4. Create Credentials:
   - Click **Create Credentials** > **OAuth client ID**.
   - Application type: **Desktop app**.
   - Download the client secret JSON file.
5. Authenticate Gmail:

```bash
uv run job-tracker auth gmail --secret-file /path/to/client_secret.json
```

Follow the browser prompt to grant read-only access. Credentials will be saved securely to `~/.config/job-tracker/tokens.json`.

---

### 3. Microsoft Azure Setup (Outlook / Microsoft 365)

Works with work/school accounts and **Personal Microsoft Accounts** (`@outlook.com`, `@hotmail.com`, `@live.com`).

1. Open [Azure Portal App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade).
2. Click **New registration**:
   - Name: `Job Tracker`
   - Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**.
3. Configure Redirect URI:
   - Under **Authentication** > **Platform configurations**, click **Add a platform** > **Mobile and desktop applications**.
   - Select and check: `https://login.live.com/oauth20_desktop.srf`
   - Click **Configure**.
4. Enable Public Client Flows:
   - Under **Authentication** > **Advanced settings**, set **Allow public client flows** to **Yes**.
5. Add API Permissions:
   - Go to **API permissions** > **Add a permission** > **Microsoft Graph** > **Delegated permissions**.
   - Add:
     - `Mail.Read`
     - `User.Read`
     - `offline_access`
6. Copy the **Application (client) ID** from the Overview tab.
7. Run the auth command:

```bash
uv run job-tracker auth outlook --client-id "<AZURE_CLIENT_ID>"
```

A browser window will open to sign in and grant consent. Once completed, your browser will redirect to `https://login.live.com/oauth20_desktop.srf?code=...`. Copy that full URL and paste it into the prompt (or run `uv run job-tracker auth outlook --redeem "<PASTED_URL>"`).

---

### 4. LLM API Key (Google Gemini or Ollama)

#### Option A: Google Gemini (Recommended)
1. Get an API key from [Google AI Studio](https://aistudio.google.com/).
2. Add it to `~/.config/job-tracker/config.toml` under `[llm]`:

```toml
[llm]
provider = "gemini"
model_name = "gemini-3-flash-preview"
api_key = "AIzaSy..."
```

*(Alternatively, export `export GEMINI_API_KEY="AIzaSy..."` in your environment).*

#### Option B: Local Ollama
1. Install [Ollama](https://ollama.ai/) and pull a lightweight model:
   ```bash
   ollama pull llama3.2
   ```
2. Update `~/.config/job-tracker/config.toml`:
   ```toml
   [llm]
   provider = "ollama"
   model_name = "llama3.2"
   api_base = "http://localhost:11434"
   ```

---

## Running the Agent

### Dry Run (Preview Only)
Preview what the agent finds across your inboxes without writing to Notion:

```bash
uv run job-tracker sync --dry-run
```

### Live Sync
Run a real synchronization across inboxes with an optional backfill window:

```bash
uv run job-tracker sync --backfill-days 14
```

---

## Background Automation (systemd)

The agent runs as a systemd user timer, meaning it runs entirely in your user session without needing root permissions.

### Install & Enable Weekly Timer
To run weekly every Monday at 00:00:00:

```bash
# Install systemd service and weekly timer
uv run job-tracker service install --schedule weekly

# Enable and start the timer
systemctl --user start job-tracker.timer

# Verify the timer schedule
systemctl --user list-timers job-tracker.timer
```

### Change Interval
If you prefer 30-minute intervals:

```bash
uv run job-tracker service install --interval 30
systemctl --user restart job-tracker.timer
```

### Monitor Background Runs

```bash
# Check timer status
uv run job-tracker service status

# View journal logs from sync runs
uv run job-tracker service logs -n 50
```

---

## Configuration Reference

The main configuration file is stored at `~/.config/job-tracker/config.toml`:

```toml
[notion]
api_key = "ntn_..."
database_id = "5f0a7d8e142d48e2aba15fdc2e9ba52e"
parent_page_id = "391a93a1affd83da8ab9015e51763e3c"

[outlook]
client_id = "1321c58a-7b6a-423f-b2bd-a01b1104ac72"

[llm]
provider = "gemini"
model_name = "gemini-3-flash-preview"
api_key = "AIzaSy..."

[sync]
backfill_days = 14
polling_interval_minutes = 30
desktop_alerts = true
```

---

## Development & Testing

Run the test suite:

```bash
uv run pytest
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
