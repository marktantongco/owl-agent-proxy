#!/usr/bin/env python3
"""Verify the vendored skills against skills-lock.json.

The point of a lock file is that someone can check it. Version 1 of
`skills-lock.json` could not be: its `computedHash` values matched no upstream
revision of any of the six files, and no whitespace or frontmatter normalisation
of them either. It was decorative, and it had drifted from the tree since the day
it was written.

Version 2 records two things that *can* be checked:

* `upstreamCommit` — the commit whose blob produced the vendored content, so
  `main` moving upstream does not silently change what this repo ships;
* `contentHash` — `sha256:` of the vendored file's raw bytes, exactly as
  committed.

Modes
-----
    python scripts/verify-skills-lock.py            # offline: vendored files vs lock
    python scripts/verify-skills-lock.py --remote    # also re-fetch each pinned commit
    python scripts/verify-skills-lock.py --update    # re-pin + rehash (needs network)

`--remote` is not in CI: a network hiccup must not turn a green build red. It is
what you run when bumping a skill. Anything declared in `localModification` is
verified structurally instead of by byte equality — the body must not contain
further differences, or the check fails.

Stdlib only.

Rules enforced — see scripts/gen-docs.py for the `gate:` convention:

gate: vendored-files-present: every lock entry's vendoredPath exists [required]
gate: vendored-bytes-match-pin: vendored content matches the pinned upstream commit, unless a localModification is declared [required]
gate: lock-is-checkable: --update must be able to record a verifiable hash [required]
"""

from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "skills-lock.json"


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def api(url: str) -> dict | list:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_at_commit(repo: str, path: str, ref: str) -> bytes:
    payload = api(f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}")
    return base64.b64decode(payload["content"])


def body_of(text: str) -> str:
    """Everything after the closing frontmatter fence."""
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    return parts[2] if len(parts) == 3 else text


def check_local(skills: dict) -> list[str]:
    problems: list[str] = []
    for name, entry in sorted(skills.items()):
        path = ROOT / entry["vendoredPath"]
        if not path.is_file():
            problems.append(f"{name}: vendoredPath missing — {entry['vendoredPath']}")
            continue
        actual = sha256_file(path)
        if actual != entry["contentHash"]:
            problems.append(
                f"{name}: content hash mismatch\n"
                f"    lock    {entry['contentHash']}\n"
                f"    actual  {actual}\n"
                f"    -> the vendored file changed; re-pin with --update or revert it"
            )
    return problems


def check_remote(skills: dict) -> list[str]:
    """Re-fetch each pinned commit and compare with what is vendored."""
    problems: list[str] = []
    for name, entry in sorted(skills.items()):
        local = ROOT / entry["vendoredPath"]
        if not local.is_file():
            continue
        try:
            upstream = fetch_at_commit(entry["source"], entry["skillPath"], entry["upstreamCommit"])
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            problems.append(f"{name}: could not fetch {entry['source']}@{entry['upstreamCommit'][:10]}: {exc}")
            continue

        vendored = local.read_bytes()
        if vendored == upstream:
            print(f"  OK    {name}: byte-identical to pinned commit")
            continue

        mod = entry.get("localModification")
        if not mod:
            problems.append(f"{name}: differs from pinned commit {entry['upstreamCommit'][:10]} and declares no localModification")
            continue

        # A declared modification is only acceptable if it is frontmatter-only.
        a = upstream.decode("utf-8", "replace")
        b = vendored.decode("utf-8", "replace")
        if body_of(a) == body_of(b):
            print(f"  OK    {name}: declared local modification, body identical to pinned commit")
        else:
            diff = "\n".join(
                list(difflib.unified_diff(body_of(a).splitlines(), body_of(b).splitlines(),
                                          "upstream-body", "vendored-body", lineterm=""))[:12]
            )
            problems.append(
                f"{name}: declares a frontmatter-only localModification but the body differs\n{diff}"
            )
    return problems


def update() -> int:
    """Re-pin every skill to upstream HEAD and rewrite the hashes."""
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for name, entry in sorted(lock["skills"].items()):
        local = ROOT / entry["vendoredPath"]
        commits = api(f"https://api.github.com/repos/{entry['source']}/commits?path={entry['skillPath']}&per_page=1")
        commit = commits[0]
        entry["upstreamCommit"] = commit["sha"]
        entry["upstreamCommitDate"] = commit["commit"]["committer"]["date"][:10]
        entry["contentHash"] = sha256_file(local)

        upstream = fetch_at_commit(entry["source"], entry["skillPath"], commit["sha"])
        if local.read_bytes() == upstream:
            entry.pop("localModification", None)
            print(f"re-pinned {name} -> {commit['sha'][:10]} (identical)")
        else:
            entry.setdefault(
                "localModification",
                "vendored copy differs from upstream; inspect before shipping",
            )
            print(f"re-pinned {name} -> {commit['sha'][:10]} (DIFFERS — localModification kept)")

    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {LOCK.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", action="store_true", help="also re-fetch each pinned upstream commit")
    parser.add_argument("--update", action="store_true", help="re-pin to upstream HEAD and rehash (network)")
    args = parser.parse_args()

    if args.update:
        return update()

    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if lock.get("version") != 2:
        print(f"FAIL: {LOCK.name} is version {lock.get('version')}; expected 2")
        return 1

    skills = lock["skills"]
    problems = check_local(skills)
    print(f"offline: {len(skills) - len([p for p in problems])} of {len(skills)} vendored files match the lock")

    if args.remote:
        print("\nremote: re-fetching pinned commits")
        problems.extend(check_remote(skills))

    if problems:
        print(f"\nFAILED: {len(problems)} provenance problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"\nPASSED: {len(skills)} skill(s) verified" + (" against pinned commits" if args.remote else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
