import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
UPDATER = ROOT / "update_ptis.py"


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def init_repo(path: Path) -> None:
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "PTIS Test")
    git(path, "config", "user.email", "ptis-test@example.invalid")


def commit_all(path: Path, message: str) -> None:
    git(path, "add", "-A")
    git(path, "commit", "-m", message)


def make_upstream(path: Path, version: str = "2.0.0") -> None:
    init_repo(path)
    (path / ".ptis").mkdir(parents=True, exist_ok=True)
    (path / "PTIS_VERSION").write_text(version + "\n", encoding="utf-8")
    (path / "managed.txt").write_text("new managed\n", encoding="utf-8")
    (path / "user_config.json").write_text(
        '{"focus_search":{"enabled":false}}\n',
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "managed_files": [
            ".ptis/update_manifest.json",
            "PTIS_VERSION",
            "managed.txt",
        ],
        "seed_if_missing": ["user_config.json"],
        "protected_files": [
            "data/state.json",
            "data/kakao_auth.json",
            "user_config.json",
        ],
        "remove_files": [],
    }
    (path / ".ptis" / "update_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    commit_all(path, "upstream")


def make_target(path: Path, *, with_config: bool = True, version: str | None = None) -> None:
    init_repo(path)
    (path / "data").mkdir(parents=True, exist_ok=True)
    (path / "managed.txt").write_text("old managed\n", encoding="utf-8")
    (path / "data" / "state.json").write_bytes(b'{"route_history":{"LOCAL":[]}}\n')
    (path / "data" / "kakao_auth.json").write_bytes(b'{"ciphertext":"LOCAL"}\n')
    if with_config:
        (path / "user_config.json").write_bytes(
            b'{"focus_search":{"enabled":true,"region":"LOCAL"}}\n'
        )
    if version is not None:
        (path / "PTIS_VERSION").write_text(version + "\n", encoding="utf-8")
    commit_all(path, "installed")


def run_updater(target: Path, upstream: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(UPDATER),
            *extra,
            "--upstream",
            str(upstream),
            "--branch",
            "main",
        ],
        cwd=target,
        text=True,
        capture_output=True,
    )


class UpdateManifestTests(unittest.TestCase):
    def test_current_manifest_references_existing_upstream_files(self):
        manifest_path = ROOT / ".ptis" / "update_manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        managed = set(payload["managed_files"])
        protected = set(payload["protected_files"])
        seeds = set(payload["seed_if_missing"])

        self.assertTrue(managed)
        self.assertTrue(managed.isdisjoint(protected))
        self.assertEqual(seeds.intersection(protected), {"user_config.json"})
        self.assertNotIn("TASK.md", managed)
        self.assertNotIn("CHECKPOINT.md", managed)

        for rel in sorted(managed | seeds):
            self.assertTrue((ROOT / rel).exists(), rel)


class InstalledUpdateIntegrationTests(unittest.TestCase):
    def test_legacy_update_replaces_managed_and_preserves_personal_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            upstream = base / "upstream"
            target = base / "target"
            upstream.mkdir()
            target.mkdir()
            make_upstream(upstream)
            make_target(target, with_config=True)

            before_state = (target / "data" / "state.json").read_bytes()
            before_auth = (target / "data" / "kakao_auth.json").read_bytes()
            before_config = (target / "user_config.json").read_bytes()

            result = run_updater(target, upstream, "--apply", "--yes")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("installed version: legacy", result.stdout)
            self.assertEqual(
                (target / "managed.txt").read_text(encoding="utf-8"),
                "new managed\n",
            )
            self.assertEqual(
                (target / "PTIS_VERSION").read_text(encoding="utf-8"),
                "2.0.0\n",
            )
            self.assertEqual((target / "data" / "state.json").read_bytes(), before_state)
            self.assertEqual((target / "data" / "kakao_auth.json").read_bytes(), before_auth)
            self.assertEqual((target / "user_config.json").read_bytes(), before_config)

    def test_missing_user_config_is_seeded_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            upstream = base / "upstream"
            target = base / "target"
            upstream.mkdir()
            target.mkdir()
            make_upstream(upstream)
            make_target(target, with_config=False)

            result = run_updater(target, upstream, "--apply", "--yes")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (target / "user_config.json").read_text(encoding="utf-8"),
                '{"focus_search":{"enabled":false}}\n',
            )

    def test_dirty_worktree_refuses_apply_without_touching_managed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            upstream = base / "upstream"
            target = base / "target"
            upstream.mkdir()
            target.mkdir()
            make_upstream(upstream)
            make_target(target)
            (target / "local-note.txt").write_text("dirty\n", encoding="utf-8")

            result = run_updater(target, upstream, "--apply", "--yes")

            self.assertEqual(result.returncode, 1)
            self.assertIn("Working tree is not clean", result.stderr)
            self.assertEqual(
                (target / "managed.txt").read_text(encoding="utf-8"),
                "old managed\n",
            )
            self.assertFalse((target / "PTIS_VERSION").exists())

    def test_same_version_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            upstream = base / "upstream"
            target = base / "target"
            upstream.mkdir()
            target.mkdir()
            make_upstream(upstream, version="2.0.0")
            make_target(target, version="2.0.0")

            result = run_updater(target, upstream, "--apply", "--yes")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("No newer PTIS version is available.", result.stdout)
            self.assertEqual(
                (target / "managed.txt").read_text(encoding="utf-8"),
                "old managed\n",
            )
            status = git(target, "status", "--porcelain").stdout
            self.assertEqual(status, "")

    def test_check_mode_does_not_modify_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            upstream = base / "upstream"
            target = base / "target"
            upstream.mkdir()
            target.mkdir()
            make_upstream(upstream)
            make_target(target)

            result = run_updater(target, upstream, "--check")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Update available.", result.stdout)
            self.assertEqual(
                (target / "managed.txt").read_text(encoding="utf-8"),
                "old managed\n",
            )
            self.assertFalse((target / "PTIS_VERSION").exists())
            self.assertEqual(git(target, "status", "--porcelain").stdout, "")


if __name__ == "__main__":
    unittest.main()
