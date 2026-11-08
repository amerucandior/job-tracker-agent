# Job Tracker Agent

An automated background agent that ingests job application emails across Gmail and Outlook, extracts hiring status changes using an LLM, and synchronizes a structured Notion job board.

## Language

**Application**:
A single job candidacy pursued by the user at an employer for a specific position.
_Avoid_: Job, posting, lead, submission

**Application Stage**:
The current milestone in an application's hiring pipeline (`Applied`, `Screening`, `Interview`, `Offer`, `Rejected`, `Archived`).
_Avoid_: Status, step, level

**Review Flag**:
A marker applied to an application or activity entry indicating ambiguity or low model confidence requiring human verification.
_Avoid_: Warning, error, unconfirmed

**Activity Entry**:
A timestamped record of an email communication, interview invite, or status update associated with an application.
_Avoid_: Note, log, interaction, event

**Timeline Callout**:
A collapsible block appended to an Application's Notion page body containing the communication timestamp, subject, extracted summary, and action items.
_Avoid_: Comment, attachment, audit row

**Ingestion Account**:
An authenticated user mailbox (Gmail or Outlook) monitored by the agent via OAuth2 credentials.
_Avoid_: Mailbox, inbox, provider connection

**Sync Checkpoint**:
The local watermark recording the highest processed message identifier and timestamp per ingestion account.
_Avoid_: Cursor, sync state, bookmark

**Backfill Window**:
The time-bounded historical range of emails ingested during initial setup before switching to forward incremental sync.
_Avoid_: Historical scrape, import range

**Heuristic Pre-filter**:
A deterministic screening check matching known ATS sender domains and recruiting keywords to reject irrelevant email before invoking an LLM.
_Avoid_: Spam filter, regex screener

**Provisioned Board**:
A Notion database created with standard properties (`Company`, `Role`, `Stage`, `Review Flag`, `Last Activity`, `Thread IDs`) by the setup utility.
_Avoid_: Managed table, target schema

**Service Timer**:
A user-level systemd timer unit triggering periodic batch synchronization runs on a scheduled cadence.
_Avoid_: Cron job, daemon loop

**Desktop Alert**:
A transient desktop notification dispatched via libnotify when an Application stage transitions or a Review Flag is raised.
_Avoid_: Popup, toast message, push alert



