import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import report_to_ketryx as r  # noqa: E402

SHA_A = "a" * 40
SHA_B = "b" * 40
VERSIONS = [
    {"id": "KXVSN1", "name": "1.1.0"},
    {"id": "KXVSN2", "name": "1.2.0"},
]


def repo(url, commit=SHA_A, **extra):
    return {"url": url, "commit": commit, **extra}


class RepoSettingsTest(unittest.TestCase):
    def test_uses_connected_url_spelling(self):
        m = {"repos": [repo("https://github.com/acme/firmware", commit=SHA_A.upper(), tag="v4.1.0")]}
        settings, rows = r.repo_settings(m, ["https://github.com/Acme/Firmware.git"])
        self.assertEqual(
            settings, [{"url": "https://github.com/Acme/Firmware.git", "releaseRefPattern": SHA_A}]
        )
        self.assertEqual(rows, [("github.com/acme/firmware", "v4.1.0", SHA_A, "set")])

    def test_ignores_user_prefix_and_trailing_slash(self):
        m = {"repos": [repo("https://gitlab.example.com/acme/devices/firmware/")]}
        settings, _ = r.repo_settings(m, ["https://oauth2@gitlab.example.com/acme/devices/firmware.git"])
        self.assertEqual(len(settings), 1)

    def test_several_repos_some_unconnected(self):
        m = {"repos": [
            repo("https://github.com/acme/firmware"),
            repo("https://github.com/acme/app", commit=SHA_B),
            repo("https://svn.example.com/legacy", commit=""),
        ]}
        settings, rows = r.repo_settings(
            m, ["https://github.com/acme/firmware", "https://github.com/acme/app"]
        )
        self.assertEqual([s["releaseRefPattern"] for s in settings], [SHA_A, SHA_B])
        self.assertEqual(rows[2][3], "skipped: not connected in Ketryx")

    def test_extra_keys_are_ignored(self):
        m = {"release": "1.2.0", "repos": [repo("https://github.com/acme/firmware", owner="team-a")]}
        settings, _ = r.repo_settings(m, ["https://github.com/acme/firmware"])
        self.assertEqual(len(settings), 1)

    def test_bad_commit_on_connected_repo_fails(self):
        m = {"repos": [repo("https://github.com/acme/firmware", commit="1ffbb97")]}
        with self.assertRaisesRegex(r.ReportError, "for: github.com/acme/firmware"):
            r.repo_settings(m, ["https://github.com/acme/firmware"])

    def test_no_repos_fails(self):
        for m in ({}, {"repos": []}, {"repos": "https://github.com/acme/firmware"}):
            with self.assertRaisesRegex(r.ReportError, r"no \[\[repos\]\] entries"):
                r.repo_settings(m, [])

    def test_entry_without_url_fails(self):
        with self.assertRaisesRegex(r.ReportError, "entry 2 has no url"):
            r.repo_settings({"repos": [repo("https://github.com/acme/a"), {"commit": SHA_A}]}, [])


class ResolveVersionsTest(unittest.TestCase):
    def test_by_name_and_id(self):
        found = r.resolve_versions(VERSIONS, ["1.1.0", "KXVSN2"])
        self.assertEqual([v["id"] for v in found], ["KXVSN1", "KXVSN2"])

    def test_missing_fails(self):
        with self.assertRaisesRegex(r.ReportError, "'1.2'"):
            r.resolve_versions(VERSIONS, ["1.2"])

    def test_empty_input_fails(self):
        with self.assertRaises(r.ReportError):
            r.parse_list(" , ")


class FakeKetryx:
    def __init__(self):
        self.calls = []

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/versions":
            return {"versions": VERSIONS}
        if path == "/repositories":
            return {"repositories": [{"url": "https://github.com/acme/firmware"}]}
        return {}

    def version_link(self, version_id):
        return f"https://ketryx.example/versions/{version_id}/settings"

    def written(self):
        return [path.rsplit("/", 1)[1] for method, path, _ in self.calls if method == "PATCH"]


class ReportTest(unittest.TestCase):
    def setUp(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
        f.write(f'[[repos]]\nurl = "https://github.com/acme/firmware"\ncommit = "{SHA_A}"\ntag = "v4.1.0"\n')
        f.close()
        self.addCleanup(os.unlink, f.name)
        self.manifest = f.name

    def test_writes_the_version(self):
        k = FakeKetryx()
        text, errors = r.report(k, self.manifest, ["1.2.0"])
        self.assertEqual(errors, [])
        self.assertEqual(k.written(), ["KXVSN2"])
        self.assertIn("Ketryx version 1.2.0: updated", text)

    def test_missing_version_writes_nothing(self):
        k = FakeKetryx()
        with self.assertRaises(r.ReportError):
            r.report(k, self.manifest, ["9.9.9"])
        self.assertEqual(k.written(), [])

    def test_dry_run_writes_nothing(self):
        k = FakeKetryx()
        text, _ = r.report(k, self.manifest, ["1.2.0"], dry_run=True)
        self.assertEqual(k.written(), [])
        self.assertIn("would update", text)


if __name__ == "__main__":
    unittest.main()
