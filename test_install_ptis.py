import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_ptis


class RepositorySlugTests(unittest.TestCase):
    def test_https_remote(self):
        self.assertEqual(
            install_ptis._parse_repository_slug(
                "https://github.com/example/flight-bot.git"
            ),
            "example/flight-bot",
        )

    def test_ssh_remote(self):
        self.assertEqual(
            install_ptis._parse_repository_slug("git@github.com:example/flight-bot.git"),
            "example/flight-bot",
        )

    def test_non_github_remote_is_rejected(self):
        with self.assertRaises(install_ptis.InstallError):
            install_ptis._parse_repository_slug("https://example.com/repo.git")


class SecretTests(unittest.TestCase):
    @patch("install_ptis._run")
    def test_secret_value_is_sent_on_stdin(self, run):
        install_ptis._set_repository_secret("example/flight-bot", "TOKEN", "secret")
        run.assert_called_once_with(
            ["gh", "secret", "set", "TOKEN", "--repo", "example/flight-bot"],
            input_text="secret",
        )

    @patch("install_ptis._run")
    def test_dirty_worktree_is_rejected(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, stdout=" M main.py\n")
        with self.assertRaises(install_ptis.InstallError):
            install_ptis._require_clean_worktree()


class GitIdentityTests(unittest.TestCase):
    @patch("install_ptis._run")
    def test_missing_local_identity_uses_authenticated_github_noreply(self, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 1, stdout=""),
            subprocess.CompletedProcess([], 1, stdout=""),
            subprocess.CompletedProcess([], 0, stdout='{"login":"alice","id":123}\n'),
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0),
        ]
        install_ptis._ensure_local_git_identity()
        self.assertEqual(
            run.call_args_list[3].args[0],
            ["git", "config", "--local", "user.name", "alice"],
        )
        self.assertEqual(
            run.call_args_list[4].args[0],
            ["git", "config", "--local", "user.email", "123+alice@users.noreply.github.com"],
        )


class StateInitializationTests(unittest.TestCase):
    def test_runtime_history_is_reset_only_after_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            state_file.write_text(
                json.dumps({"route_history": {"ICN->X": [{"price": 1}]}, "api_usage": {"count": 3}}),
                encoding="utf-8",
            )
            with patch.object(install_ptis, "STATE_FILE", state_file), \
                 patch("builtins.input", return_value="y"):
                self.assertTrue(install_ptis._prepare_runtime_state(preserve_state=False))
            self.assertEqual(json.loads(state_file.read_text(encoding="utf-8")), install_ptis.FRESH_STATE)

    def test_preserve_state_flag_does_not_modify_history(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            original = {"route_history": {"ICN->X": [{"price": 1}]}}
            state_file.write_text(json.dumps(original), encoding="utf-8")
            with patch.object(install_ptis, "STATE_FILE", state_file):
                self.assertFalse(install_ptis._prepare_runtime_state(preserve_state=True))
            self.assertEqual(json.loads(state_file.read_text(encoding="utf-8")), original)


class OAuthRetryTests(unittest.TestCase):
    @patch("install_ptis.generate_encryption_key", return_value="new-key")
    @patch("install_ptis._prompt_secret", side_effect=["new-rest", "new-secret"])
    @patch("install_ptis._run_kakao_oauth")
    def test_failed_oauth_can_change_only_kakao_values(self, oauth, prompt_secret, generate_key):
        oauth.side_effect = [subprocess.CalledProcessError(1, ["python"]), None]
        with patch("builtins.input", return_value="c"):
            result = install_ptis._oauth_until_success("old-rest", "old-secret", "old-key")
        self.assertEqual(result, ("new-rest", "new-secret", "new-key"))
        self.assertEqual(oauth.call_count, 2)
        self.assertEqual(prompt_secret.call_count, 2)


if __name__ == "__main__":
    unittest.main()
