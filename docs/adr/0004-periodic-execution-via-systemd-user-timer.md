# Periodic Execution via systemd User Timer

We run batch synchronization via a native systemd user timer (`~/.config/systemd/user/job-tracker.timer`) invoking an ephemeral service unit rather than keeping a long-running Python process alive.

A systemd user timer consumes zero background CPU or RAM between intervals, cleanly captures standard output and error in `journalctl`, automatically restarts across reboots, and avoids orphaned processes or memory leaks inherent in continuous long-running polling scripts.
