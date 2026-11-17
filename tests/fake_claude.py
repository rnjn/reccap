#!/usr/bin/env python3
import json
import os
import sys
import time

mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": sys.stdin.read()}) + "\n")
if mode == "slow":
    time.sleep(10)
if mode == "fail":
    sys.stderr.write("not logged in\n")
    sys.exit(1)
print(os.environ.get("FAKE_CLAUDE_REPLY", "Fix retry backoff in the webhook sender"))
