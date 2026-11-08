# Local SQLite Checkpointing Over Mailbox Mutation

We track processed message IDs, timestamps, and account watermarks in a local SQLite database rather than mutating the user's remote mailbox with labels or folders.

Gmail and Outlook have diverging folder/label semantics, and adding custom labels to personal accounts modifies the user's inbox view without adding reliability. A local SQLite store provides a uniform, provider-agnostic checkpoint ledger and prevents duplicate LLM processing without touching user mail state.
