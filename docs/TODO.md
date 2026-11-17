# TODO

- **Build day pages automatically.** Add a config flag that makes the hourly `reccap sync` also rebuild today's and yesterday's day pages. Turn it on for one machine only, since `daily/` is the one path all machines share and two machines rebuilding the same page would hit push conflicts.
