# In-Page Timeline Callouts Over Relational Activity Database

We store historical email communications and stage update logs as appended collapsible callout blocks in each Application page's body rather than maintaining a separate relational `Activities` database in Notion.

A second linked database requires two-way relational queries, doubles API round-trips for every email sync, and complicates the visual interface for mobile/desktop reading. Collapsible blocks inside the page body keep all chronological context, summaries, and action items visible in a single place when clicking into a candidacy.
