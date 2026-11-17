# TODO

- **Build day pages automatically.** Add a config flag that makes the hourly `reccap sync` also rebuild today's and yesterday's day pages. Turn it on for one machine only, since `daily/` is the one path all machines share and two machines rebuilding the same page would hit push conflicts.
- **Backfill day pages.** Script `reccap day` over every date that has sessions, once all machines have synced their history.
