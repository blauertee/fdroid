#!/usr/bin/env python3
"""Fail unless the generated index lists every expected app version."""

import json
import sys
from pathlib import Path

repo, expected_file = Path(sys.argv[1]), Path(sys.argv[2])
expected = json.loads(expected_file.read_text())
index = json.loads((repo / "index-v2.json").read_text())
packages = index.get("packages", {})

errors = []
for appid, versions in expected.items():
    listed = {v["manifest"]["versionCode"]
              for v in packages.get(appid, {}).get("versions", {}).values()}
    for v in versions:
        for code in v["versionCodes"]:
            if code not in listed:
                errors.append(f"{appid} versionCode {code} ({v['tag']}) "
                              f"missing from index-v2.json (has {sorted(listed)})")
unexpected = sorted(set(packages) - set(expected))
if unexpected:
    errors.append(f"unexpected apps in index: {', '.join(unexpected)}")

for e in errors:
    print(f"::error::{e}", file=sys.stderr)
if errors:
    sys.exit(1)
print(f"index OK: {sum(len(v) for v in expected.values())} release(s) "
      f"of {len(expected)} app(s)")
