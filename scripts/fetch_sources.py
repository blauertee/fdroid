#!/usr/bin/env python3
"""Download and verify the APKs listed in sources/*.yml.

For each source file, the current revision and older revisions from its git
history are read newest first, and the APKs of up to KEEP distinct release tags
are downloaded into the output directory. Every APK is checked against the
sha256 recorded in the revision that listed it, and against the
applicationId the source file is named after.

A tag counts as one version even when its per-ABI APKs carry different
versionCodes (Flutter's --split-per-abi does that). Writes a JSON file
mapping each published applicationId to the tags and versionCodes that must
appear in the generated index.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from fdroidserver.common import get_apk_id

KEYS = {"repo": str, "tag": str, "commit": str, "apks": list}
APPID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
REPO_RE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
COMMIT_RE = re.compile(r"^([0-9a-f]{40})?$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.apk$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SourceError(Exception):
    pass


def validate(text, where):
    """Parse and strictly validate one revision of a source file."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SourceError(f"{where}: not valid YAML: {e}")
    if not isinstance(data, dict):
        raise SourceError(f"{where}: top level must be a mapping")
    missing = sorted(set(KEYS) - set(data))
    unknown = sorted(set(data) - set(KEYS))
    if missing:
        raise SourceError(f"{where}: missing key(s): {', '.join(missing)}")
    if unknown:
        raise SourceError(f"{where}: unknown key(s): {', '.join(unknown)}")
    for key, typ in KEYS.items():
        if not isinstance(data[key], typ):
            raise SourceError(
                f"{where}: '{key}' must be a {typ.__name__}, "
                f"got {type(data[key]).__name__}")
    if not REPO_RE.match(data["repo"]):
        raise SourceError(f"{where}: 'repo' must look like owner/name")
    if data["tag"] and not TAG_RE.match(data["tag"]):
        raise SourceError(f"{where}: 'tag' has invalid characters")
    if not COMMIT_RE.match(data["commit"]):
        raise SourceError(f"{where}: 'commit' must be 40 lowercase hex chars or empty")
    if bool(data["tag"]) != bool(data["apks"]):
        raise SourceError(f"{where}: 'tag' and 'apks' must both be empty or both be set")
    names = set()
    for i, apk in enumerate(data["apks"]):
        if not isinstance(apk, dict) or set(apk) != {"name", "sha256"}:
            raise SourceError(f"{where}: apks[{i}] must have exactly 'name' and 'sha256'")
        if not isinstance(apk["name"], str) or not NAME_RE.match(apk["name"]):
            raise SourceError(f"{where}: apks[{i}].name is not a plain .apk file name")
        if not isinstance(apk["sha256"], str) or not SHA256_RE.match(apk["sha256"]):
            raise SourceError(f"{where}: apks[{i}].sha256 must be 64 lowercase hex chars")
        if apk["name"] in names:
            raise SourceError(f"{where}: apks[{i}].name is listed twice")
        names.add(apk["name"])
    return data


def history(path):
    """Yield (commit, text) for older revisions of path, newest first."""
    log = subprocess.run(
        ["git", "log", "--format=%H", "--", str(path)],
        check=True, capture_output=True, text=True).stdout.split()
    for commit in log:
        show = subprocess.run(["git", "show", f"{commit}:{path}"],
                              capture_output=True, text=True)
        if show.returncode == 0:
            yield commit[:12], show.stdout


def fetch_version(appid, src, where, tmp):
    """Download and verify one revision's APKs. Returns [(versionCode, name, file)]."""
    files = []
    for apk in src["apks"]:
        url = (f"https://github.com/{src['repo']}/releases/download/"
               f"{src['tag']}/{apk['name']}")
        dest = tmp / f"{src['tag']}-{apk['name']}"
        print(f"  downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest != apk["sha256"]:
            raise SourceError(f"{where}: sha256 mismatch for {apk['name']}: "
                              f"expected {apk['sha256']}, got {digest}")
        got_id, code, _ = get_apk_id(str(dest))
        if got_id != appid:
            raise SourceError(f"{where}: {apk['name']} is {got_id}, not {appid}")
        files.append((int(code), apk["name"], dest))
    return files


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sources", type=Path, default=Path("sources"))
    p.add_argument("--metadata", type=Path, default=Path("metadata"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--expected", type=Path, required=True)
    p.add_argument("--keep", type=int, default=2)
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    expected = {}
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for path in sorted(args.sources.glob("*.yml")):
            appid = path.stem
            if not APPID_RE.match(appid):
                raise SourceError(f"{path}: file name is not an applicationId")
            current = validate(path.read_text(), str(path))
            if not current["tag"]:
                print(f"{path}: empty tag, nothing to publish yet")
                continue
            if not (args.metadata / f"{appid}.yml").is_file():
                raise SourceError(f"{path}: no {args.metadata}/{appid}.yml")
            print(f"{appid}:")
            kept, seen_tags = [], set()
            revisions = [("working tree", path.read_text())] + list(history(path))
            for rev, text in revisions:
                if len(kept) == args.keep:
                    break
                where = f"{path} @ {rev}"
                if rev == "working tree":
                    src = current
                else:
                    try:
                        src = validate(text, where)
                    except SourceError as e:
                        print(f"  skipping old revision: {e}")
                        continue
                if not src["tag"] or src["tag"] in seen_tags:
                    continue
                seen_tags.add(src["tag"])
                try:
                    files = fetch_version(appid, src, where, tmp)
                except urllib.error.HTTPError as e:
                    if not kept:
                        raise SourceError(f"{where}: download failed: {e}")
                    print(f"::warning::{appid}: skipping old release {src['tag']}: {e}")
                    continue
                codes = sorted({c for c, _, _ in files})
                if len(codes) != len(files):
                    raise SourceError(f"{where}: two APKs share a versionCode")
                if clash := sorted(set(codes) & {c for _, cs in kept for c in cs}):
                    print(f"  skipping {src['tag']}: versionCode(s) {clash} already kept")
                    continue
                kept.append((src["tag"], codes))
                for code, name, f in files:
                    shutil.move(f, args.out / f"{appid}_{code}_{name}")
                print(f"  kept {src['tag']} (versionCodes {codes})")
            if len(kept) < args.keep:
                print(f"::warning::{appid}: only {len(kept)} of {args.keep} versions available")
            expected[appid] = [{"tag": t, "versionCodes": cs} for t, cs in kept]

    args.expected.write_text(json.dumps(expected, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except SourceError as e:
        print(f"::error::{e}", file=sys.stderr)
        sys.exit(1)
