#!/usr/bin/env python3
"""Point a Ketryx version at the commits listed in a release manifest.

Usage: report_to_ketryx.py MANIFEST --versions "1.2.0" [--dry-run]

The manifest is a TOML file with one [[repos]] entry per repository:

    [[repos]]
    url = "https://github.com/acme/firmware"
    commit = "<full 40-character commit SHA>"
    tag = "v4.1.0"  # optional, shown in the output only

For each entry whose repository is connected to the Ketryx project, this sets the
version's ref for that repository (Version > Settings > Repositories) to the entry's
commit. Other keys in the file are ignored.

--versions takes Ketryx version names, matched exactly, or IDs (KXVSN...),
comma-separated. Version numbers are not used.

Environment: KETRYX_URL, KETRYX_PROJECT_ID, KETRYX_API_KEY. The API key needs the
"List versions", "Get repositories" and "Manage version settings" scopes.
Runs in GitHub Actions or GitLab CI. Output goes to the job log, and on GitHub also
to the run summary.
"""

import argparse
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ReportError(Exception):
    pass


def normalize_url(url):
    """Comparison key for repo URLs: ignores case, a trailing .git or slash, and a user@ prefix."""
    url = re.sub(r"^(https?://)[^/@]+@", r"\1", url.strip().lower().rstrip("/"))
    return url[:-4] if url.endswith(".git") else url


def short_url(url):
    """'https://github.com/acme/firmware.git' -> 'github.com/acme/firmware.git', for the output."""
    return re.sub(r"^https?://([^/@]+@)?", "", url.strip()).rstrip("/")


def parse_list(value):
    items = [x.strip() for x in value.split(",") if x.strip()]
    if not items:
        raise ReportError("No Ketryx version given")
    return items


def resolve_versions(versions, wanted):
    """Finds each wanted version by ID or exact name. Fails if any is missing."""
    by_key = {v["name"]: v for v in versions} | {v["id"]: v for v in versions}
    missing = [w for w in wanted if w not in by_key]
    if missing:
        raise ReportError(
            "Not found in the Ketryx project: " + ", ".join(repr(m) for m in missing)
        )
    return [by_key[w] for w in wanted]


def repo_settings(manifest, connected_urls):
    """Returns (repositorySettings for the PATCH body, one summary row per repo)."""
    entries = manifest.get("repos")
    if not isinstance(entries, list) or not entries:
        raise ReportError("The manifest has no [[repos]] entries")
    connected = {normalize_url(u): u for u in connected_urls}
    settings, rows, bad = [], [], []
    for i, entry in enumerate(entries, 1):
        url = str(entry.get("url", "")).strip() if isinstance(entry, dict) else ""
        if not url:
            raise ReportError(f"[[repos]] entry {i} has no url")
        commit = str(entry.get("commit", "")).strip().lower()
        ketryx_url = connected.get(normalize_url(url))
        if not ketryx_url:
            status = "skipped: not connected in Ketryx"
        elif not SHA_RE.match(commit):
            bad.append(short_url(url))
            status = "bad commit"
        else:
            settings.append({"url": ketryx_url, "releaseRefPattern": commit})
            status = "set"
        rows.append((short_url(url), str(entry.get("tag", "")), commit, status))
    if bad:
        raise ReportError(
            "commit is missing or not a full 40-character SHA for: " + ", ".join(bad)
        )
    return settings, rows


class Ketryx:
    def __init__(self, base_url, project_id, api_key):
        self.base = base_url.rstrip("/") + f"/api/v1/projects/{project_id}"
        self.web = base_url.rstrip("/") + f"/projects/{project_id}"
        self.key = api_key

    def call(self, method, path, body=None):
        req = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise ReportError(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:500]}")

    def version_link(self, version_id):
        return f"{self.web}/versions/{version_id}/settings"


def report(ketryx, manifest_path, wanted, dry_run=False):
    """Reports one manifest to the wanted versions. Returns (plain-text summary, write errors)."""
    with open(manifest_path, "rb") as f:
        manifest = tomllib.load(f)

    # Everything is looked up and checked before any version is written.
    targets = resolve_versions(ketryx.call("GET", "/versions")["versions"], wanted)
    repos = ketryx.call("GET", "/repositories")["repositories"]
    settings, rows = repo_settings(manifest, [r["url"] for r in repos])
    if not settings:
        raise ReportError("None of the manifest's repos are connected to the Ketryx project")

    lines = [manifest_path + ("  (dry run, nothing written)" if dry_run else ""), ""]
    errors = []
    for version in targets:
        result = "would update"
        if not dry_run:
            try:
                ketryx.call("PATCH", f"/versions/{version['id']}", {"repositorySettings": settings})
                result = "updated"
            except ReportError as e:
                errors.append(f"{version['name']}: {e}")
                result = f"FAILED: {e}"
        lines += [f"Ketryx version {version['name']}: {result}", f"  {ketryx.version_link(version['id'])}"]
    table = [("Repo", "Tag", "Commit", "Ketryx")] + [(u, t, c[:12], s) for u, t, c, s in rows]
    widths = [max(len(row[i]) for row in table) for i in range(3)]
    lines.append("")
    lines += ["  ".join(c.ljust(w) for c, w in zip(row, widths)) + "  " + row[3] for row in table]
    return "\n".join(lines) + "\n", errors


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("manifest", help="release manifest TOML file")
    parser.add_argument("--versions", required=True, help="Ketryx version names or IDs, comma-separated")
    parser.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    args = parser.parse_args()

    on_github = os.environ.get("GITHUB_ACTIONS") == "true"

    def error(message):
        if on_github:
            print(f"::error::{message}")
        else:
            print(f"ERROR: {message}", file=sys.stderr)

    missing = [k for k in ("KETRYX_URL", "KETRYX_PROJECT_ID", "KETRYX_API_KEY") if not os.environ.get(k)]
    if missing:
        error(f"Not set: {', '.join(missing)}")
        sys.exit(1)
    ketryx = Ketryx(os.environ["KETRYX_URL"], os.environ["KETRYX_PROJECT_ID"], os.environ["KETRYX_API_KEY"])

    try:
        text, errors = report(ketryx, args.manifest, parse_list(args.versions), args.dry_run)
    except (ReportError, OSError, tomllib.TOMLDecodeError) as e:
        text, errors = "Not reported.\n", [str(e)]
    print(text)
    for e in errors:
        error(e)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("```\n" + text + "".join(f"ERROR: {e}\n" for e in errors) + "```\n")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
