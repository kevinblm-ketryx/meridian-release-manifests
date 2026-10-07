# Report a release to Ketryx from GitHub

For a Ketryx project built from several repos. A GitHub Action points the project's
Ketryx version at the exact commit of each repo in a release.

You list the release's repos and commits in a small manifest file, then run the
Action with that file and the Ketryx version. For each repo that's connected to the
Ketryx project, it sets the version's ref (*Version → Settings → Repositories*) to the
commit in the manifest. Ketryx then reads exactly those commits for that version.

## Before you start

- The repos are connected to your Ketryx project (*Settings → Repositories*).
- The Ketryx version for the release exists.
- You have a repo on GitHub that holds the release manifests.

## Manifest format

One TOML file per release, e.g. `releases/1.2.0.toml`, with a `[[repos]]` block for
each repo that goes into the release:

```toml
[[repos]]
url = "https://github.com/acme/firmware"
commit = "375877dfbdb7db65f040d39d9995f83b6a993e94"
tag = "v4.1.0"

[[repos]]
url = "https://github.com/acme/mobile-app"
commit = "1be738f6074c579279e1d088e91aee15f4adcfc2"
tag = "v2.3.0"

[[repos]]
url = "https://github.com/acme/cloud-api"
commit = "28a2940197f244c98a3f0d36a5e7eb2c2adf8030"
tag = "v7.0.2"
```

- `url` is the repo's HTTPS address, the same one connected in Ketryx. Case, a
  trailing `.git` or slash, and a `user@` prefix are ignored.
- `commit` must be the full 40-character commit SHA.
- `tag` is optional and only shown in the output.
- Any other keys are ignored, so you can add your own, such as `release = "1.2.0"` at
  the top.

## One-time setup

1. Copy `.github/workflows/report-to-ketryx.yml` and `scripts/report_to_ketryx.py`
   into the manifest repo, keeping their paths.
2. In the workflow file, set `KETRYX_URL` to your Ketryx address and
   `KETRYX_PROJECT_ID` to the project ID (`KXPRJ…`, from the project's URL).
3. In Ketryx, go to *Organization → API keys* and create a key with these scopes:
   *List versions*, *Get repositories*, *Manage version settings*.
4. In the manifest repo on GitHub, go to *Settings → Secrets and variables → Actions*
   and add the key as a secret named `KETRYX_API_KEY`.

## Report a release

1. Commit the release's manifest to the repo.
2. Go to *Actions → Report release to Ketryx → Run workflow* and fill in:
   - **manifest:** the path in the repo, e.g. `releases/1.2.0.toml`
   - **version:** the Ketryx version's exact name, or its ID (`KXVSN…`)
   - **dry run:** tick it for the first run
3. Read the run summary. It lists each repo with its commit, and says whether each one
   will be set or skipped.
4. Run it again with *dry run* unticked.
5. In Ketryx, open the version's *Settings → Repositories* to see the new commits.

## Good to know

- **Name, not number.** The version is matched by its name exactly as it appears in
  Ketryx (same case, spacing and punctuation), or by ID. The version number isn't used.
- **Checks before writes.** If the version isn't found, or a connected repo has a
  missing or short `commit`, the run fails without changing anything.
- **Skipped repos.** Repos in the manifest that aren't connected in Ketryx are listed
  as skipped. The rest are still written.
- **Re-runs.** Running it again with an updated manifest overwrites the commits.
- **Released versions** can't be changed. Ketryx rejects the write and the run fails.
- **Audit trail.** Each write appears in the Ketryx project's audit log under the API
  key.
- **Tests.** `tests/` is only needed if you change the script
  (`python3.12 -m unittest discover -s tests`).
