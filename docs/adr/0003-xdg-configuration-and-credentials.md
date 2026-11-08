# XDG Directory Specification for Configuration and Credentials

We store application settings, OAuth credentials, and tokens in the XDG user directory (`~/.config/job-tracker/`) rather than within the repository working directory (e.g., a project `.env`).

Keeping credentials at `~/.config/job-tracker/` (with strict `0600` permissions on token stores) prevents accidental commits of sensitive OAuth refresh tokens, enables clean single-user systemd execution without hardcoded project paths, and adheres to standard Linux desktop conventions.
