"""Guided one-command installer for a personal PTIS repository."""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import webbrowser

from kakao_auth import AUTH_FILE, generate_encryption_key


ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "data" / "state.json"
REDIRECT_URI = "http://127.0.0.1:8765/callback"
SETUP_WORKFLOW = "kakao-setup-test.yml"
MIN_PYTHON = (3, 11)
SECRET_NAMES = (
    "SERPAPI_KEY",
    "KAKAO_REST_API_KEY",
    "KAKAO_CLIENT_SECRET",
    "KAKAO_TOKEN_ENCRYPTION_KEY",
)
FRESH_STATE = {
    "route_history": {},
    "kakao_consecutive_failures": 0,
    "api_usage": {},
}


class InstallError(RuntimeError):
    """Raised when the guided installer cannot continue safely."""


def _run(args, *, input_text=None, env=None, capture=False, check=True):
    return subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        input=input_text,
        text=True,
        capture_output=capture,
        check=check,
    )


def _parse_repository_slug(remote_url: str) -> str:
    value = remote_url.strip()
    patterns = (
        r"^https://github\.com/([^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?$",
        r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return match.group(1)
    raise InstallError("The origin remote is not a supported GitHub repository URL.")


def _repository_slug() -> str:
    result = _run(
        ["git", "config", "--get", "remote.origin.url"],
        capture=True,
    )
    return _parse_repository_slug(result.stdout)


def _require_python() -> None:
    if sys.version_info < MIN_PYTHON:
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise InstallError(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required; found {version}."
        )


def _require_command(name: str) -> None:
    if not shutil.which(name):
        raise InstallError(f"Required command is missing: {name}")


def _require_clean_worktree() -> None:
    result = _run(["git", "status", "--porcelain"], capture=True)
    if result.stdout.strip():
        raise InstallError(
            "The repository has uncommitted changes. Commit or stash them before setup."
        )


def _github_identity():
    result = _run(
        ["gh", "api", "user", "--jq", "{login: .login, id: .id}"],
        capture=True,
    )
    try:
        payload = json.loads(result.stdout)
        login = str(payload["login"]).strip()
        user_id = int(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InstallError("Could not read the authenticated GitHub identity.") from exc
    if not login or user_id <= 0:
        raise InstallError("Could not read the authenticated GitHub identity.")
    return login, f"{user_id}+{login}@users.noreply.github.com"


def _ensure_local_git_identity() -> None:
    name = _run(["git", "config", "--local", "--get", "user.name"], capture=True, check=False)
    email = _run(["git", "config", "--local", "--get", "user.email"], capture=True, check=False)
    if name.returncode == 0 and name.stdout.strip() and email.returncode == 0 and email.stdout.strip():
        return

    login, noreply_email = _github_identity()
    if name.returncode != 0 or not name.stdout.strip():
        _run(["git", "config", "--local", "user.name", login])
    if email.returncode != 0 or not email.stdout.strip():
        _run(["git", "config", "--local", "user.email", noreply_email])


def _prompt_secret(label: str) -> str:
    value = getpass.getpass(f"{label}: ").strip()
    if not value:
        raise InstallError(f"{label} cannot be empty.")
    return value


def _set_repository_secret(repository: str, name: str, value: str) -> None:
    _run(
        ["gh", "secret", "set", name, "--repo", repository],
        input_text=value,
    )


def _file_snapshot(path: Path):
    return path.read_bytes() if path.exists() else None


def _restore_file(path: Path, snapshot) -> None:
    if snapshot is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(snapshot)


def _state_has_history() -> bool:
    if not STATE_FILE.exists():
        return False
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError("data/state.json is unreadable; refusing to overwrite it.") from exc
    if not isinstance(payload, dict):
        raise InstallError("data/state.json has an unsupported format; refusing to overwrite it.")
    for key in ("route_history", "exposure_log", "carryover_pool"):
        if payload.get(key):
            return True
    usage = payload.get("api_usage")
    return isinstance(usage, dict) and bool(usage.get("count"))


def _prepare_runtime_state(*, preserve_state: bool) -> bool:
    if preserve_state or not _state_has_history():
        if preserve_state:
            print("Preserving existing PTIS runtime state (--preserve-state).")
        return False

    print("\nThis repository contains PTIS runtime history from another installation or prior use.")
    print("A new personal installation must start with its own price history, exposure log, and API budget.")
    answer = input("Reset inherited runtime history for this installation? [Y/n] ").strip().lower()
    if answer not in {"", "y", "yes"}:
        raise InstallError(
            "Setup stopped before changing runtime state. Use --preserve-state only when reconfiguring an existing installation."
        )
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(FRESH_STATE, indent=2) + "\n", encoding="utf-8")
    return True


def _run_kakao_oauth(rest_key: str, client_secret: str, encryption_key: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "KAKAO_REST_API_KEY": rest_key,
            "KAKAO_CLIENT_SECRET": client_secret,
            "KAKAO_TOKEN_ENCRYPTION_KEY": encryption_key,
            "KAKAO_REDIRECT_URI": REDIRECT_URI,
        }
    )
    _run([sys.executable, "setup_kakao.py"], env=env)
    if not AUTH_FILE.exists():
        raise InstallError("Kakao OAuth completed without creating the encrypted auth file.")


def _oauth_until_success(rest_key: str, client_secret: str, encryption_key: str):
    while True:
        try:
            _run_kakao_oauth(rest_key, client_secret, encryption_key)
            return rest_key, client_secret, encryption_key
        except (subprocess.CalledProcessError, InstallError):
            print("\nKakao OAuth failed. SerpAPI and other setup values are still kept in memory.")
            choice = input("Retry same Kakao values [R], enter new Kakao values [C], or quit [Q]? ").strip().lower()
            if choice in {"", "r", "retry"}:
                continue
            if choice in {"c", "change"}:
                rest_key = _prompt_secret("Kakao REST API key")
                client_secret = _prompt_secret("Kakao Login Client Secret")
                encryption_key = generate_encryption_key()
                continue
            raise InstallError("Kakao OAuth setup cancelled before secrets were saved.")


def _save_secrets_with_retry(repository: str, values) -> None:
    while True:
        try:
            for name in SECRET_NAMES:
                _set_repository_secret(repository, name, values[name])
            return
        except subprocess.CalledProcessError:
            answer = input("Saving GitHub Secrets failed. Retry with the same in-memory values? [Y/n] ").strip().lower()
            if answer in {"", "y", "yes"}:
                continue
            raise InstallError("GitHub Secrets were not fully saved.")


def _commit_setup_files(include_state: bool) -> None:
    paths = [str(AUTH_FILE.relative_to(ROOT))]
    if include_state:
        paths.append(str(STATE_FILE.relative_to(ROOT)))
    _run(["git", "add", *paths])
    changed = _run(["git", "diff", "--cached", "--quiet"], check=False)
    if changed.returncode == 0:
        raise InstallError("The PTIS setup files did not change.")
    _run(["git", "commit", "-m", "Configure personal PTIS installation"])
    try:
        _run(["git", "push"])
    except subprocess.CalledProcessError:
        _run(["git", "reset", "--soft", "HEAD~1"], check=False)
        raise


def _latest_workflow_run(repository: str):
    result = _run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repository,
            "--workflow",
            SETUP_WORKFLOW,
            "--event",
            "workflow_dispatch",
            "--limit",
            "1",
            "--json",
            "databaseId,status,conclusion,url",
        ],
        capture=True,
    )
    rows = json.loads(result.stdout)
    return rows[0] if rows else None


def _run_delivery_test(repository: str) -> None:
    before = _latest_workflow_run(repository)
    before_id = before.get("databaseId") if before else None
    _run(
        [
            "gh",
            "workflow",
            "run",
            SETUP_WORKFLOW,
            "--repo",
            repository,
            "--ref",
            "main",
        ]
    )
    run = None
    for _ in range(20):
        time.sleep(2)
        candidate = _latest_workflow_run(repository)
        if candidate and candidate.get("databaseId") != before_id:
            run = candidate
            break
    if not run:
        raise InstallError("The Kakao verification workflow did not appear in time.")
    print(f"Verification run: {run['url']}")
    _run(
        [
            "gh",
            "run",
            "watch",
            str(run["databaseId"]),
            "--repo",
            repository,
            "--exit-status",
        ]
    )


def _secret_names(repository: str):
    result = _run(
        ["gh", "secret", "list", "--repo", repository, "--json", "name"],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return {row["name"] for row in json.loads(result.stdout)}
    except (KeyError, TypeError, json.JSONDecodeError):
        return None


def _pages_enabled(repository: str):
    result = _run(
        ["gh", "api", f"repos/{repository}/pages", "--silent"],
        capture=True,
        check=False,
    )
    return result.returncode == 0


def _doctor() -> int:
    print("PTIS setup doctor (read-only)")
    failures = 0

    python_ok = sys.version_info >= MIN_PYTHON
    print(f"[{'OK' if python_ok else 'FAIL'}] Python {sys.version.split()[0]}")
    failures += 0 if python_ok else 1

    for command in ("git", "gh"):
        found = shutil.which(command)
        print(f"[{'OK' if found else 'FAIL'}] {command} {'found' if found else 'missing'}")
        failures += 0 if found else 1
    if failures:
        return 1

    auth = _run(["gh", "auth", "status"], capture=True, check=False)
    print(f"[{'OK' if auth.returncode == 0 else 'FAIL'}] GitHub CLI authentication")
    failures += 0 if auth.returncode == 0 else 1
    if auth.returncode != 0:
        return 1

    try:
        repository = _repository_slug()
        print(f"[OK] Repository: {repository}")
    except (InstallError, subprocess.CalledProcessError):
        print("[FAIL] GitHub origin repository")
        return 1

    worktree = _run(["git", "status", "--porcelain"], capture=True, check=False)
    clean = worktree.returncode == 0 and not worktree.stdout.strip()
    print(f"[{'OK' if clean else 'WARN'}] Working tree {'clean' if clean else 'has local changes'}")

    identity_name = _run(["git", "config", "--get", "user.name"], capture=True, check=False)
    identity_email = _run(["git", "config", "--get", "user.email"], capture=True, check=False)
    identity_ok = bool(identity_name.stdout.strip() and identity_email.stdout.strip())
    print(f"[{'OK' if identity_ok else 'WARN'}] Git commit identity {'configured' if identity_ok else 'not configured yet'}")

    names = _secret_names(repository)
    if names is None:
        print("[WARN] GitHub Secrets could not be inspected")
    else:
        missing = [name for name in SECRET_NAMES if name not in names]
        if missing:
            print("[WARN] Required GitHub Secret names missing: " + ", ".join(missing))
        else:
            print("[OK] Required GitHub Secret names are present")

    auth_present = AUTH_FILE.exists()
    print(f"[{'OK' if auth_present else 'WARN'}] Encrypted Kakao auth file {'present' if auth_present else 'not present'}")
    pages_enabled = _pages_enabled(repository)
    print(f"[{'OK' if pages_enabled else 'WARN'}] GitHub Pages {'enabled' if pages_enabled else 'not confirmed'}")

    try:
        latest = _latest_workflow_run(repository)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        latest = None
        print("[WARN] Kakao verification status could not be inspected")
    else:
        if latest:
            conclusion = latest.get("conclusion") or latest.get("status") or "unknown"
            print(f"[INFO] Latest Kakao verification: {conclusion}")
        else:
            print("[INFO] Kakao verification has not run yet")
    return 1 if failures else 0


def _print_preflight(repository: str) -> None:
    print("\nPreflight complete:")
    print("[OK] Python 3.11+")
    print("[OK] Git")
    print("[OK] GitHub CLI authentication")
    print(f"[OK] Repository: {repository}")
    print("[OK] Repository-local Git commit identity")
    print("[NEEDED] SerpAPI key")
    print("[NEEDED] Kakao REST API key and Kakao Login Client Secret")


def _print_summary(status, repository: str) -> None:
    print("\nPTIS setup summary")
    print(f"- Repository: {repository}")
    print(f"- Runtime state: {'RESET' if status['state_reset'] else 'PRESERVED/EMPTY'}")
    print(f"- Kakao OAuth: {'OK' if status['oauth'] else 'NOT COMPLETED'}")
    print(f"- GitHub Secrets: {'OK' if status['secrets'] else 'NOT COMPLETED'}")
    print(f"- Encrypted token commit: {'OK' if status['commit'] else 'NOT COMPLETED'}")
    verification = status["verification"]
    print(f"- Kakao verification: {verification}")
    print(f"- GitHub Pages: {'OK' if status['pages'] else 'VERIFY IN SETTINGS'}")


def _rollback_setup_files(state_snapshot, auth_snapshot) -> None:
    _restore_file(STATE_FILE, state_snapshot)
    _restore_file(AUTH_FILE, auth_snapshot)
    _run(["git", "reset", "--quiet"], check=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doctor", action="store_true", help="Run read-only setup diagnostics.")
    parser.add_argument(
        "--preserve-state",
        action="store_true",
        help="Keep existing runtime history when reconfiguring an existing installation.",
    )
    args = parser.parse_args(argv)

    if args.doctor:
        return _doctor()

    print("PTIS Personal guided setup")
    print("Secrets stay in memory and are sent directly to GitHub Actions secrets.")
    status = {
        "state_reset": False,
        "oauth": False,
        "secrets": False,
        "commit": False,
        "verification": "NOT RUN",
        "pages": False,
    }
    repository = "unknown"
    state_snapshot = None
    auth_snapshot = None
    commit_done = False
    try:
        _require_python()
        _require_command("git")
        _require_command("gh")
        _require_clean_worktree()
        _run(["gh", "auth", "status"])
        repository = _repository_slug()
        _ensure_local_git_identity()
        _print_preflight(repository)

        state_snapshot = _file_snapshot(STATE_FILE)
        auth_snapshot = _file_snapshot(AUTH_FILE)
        status["state_reset"] = _prepare_runtime_state(preserve_state=args.preserve_state)

        owner = repository.split("/", 1)[0]
        pages_domain = f"https://{owner}.github.io"
        print("\nBefore continuing, configure your Kakao Developers app:")
        print(f"- Redirect URI: {REDIRECT_URI}")
        print(f"- Product Link web domain: {pages_domain}")
        print("- Kakao Login: ON")
        print("- Consent item talk_message: optional or required consent")
        print("- Kakao Login Client Secret: ON")
        webbrowser.open("https://developers.kakao.com/console/app")
        input("Press Enter after the Kakao app settings are complete...")

        serpapi_key = _prompt_secret("SerpAPI key")
        rest_key = _prompt_secret("Kakao REST API key")
        client_secret = _prompt_secret("Kakao Login Client Secret")
        encryption_key = generate_encryption_key()

        print("\nOpening Kakao consent. Approve KakaoTalk Message access once.")
        rest_key, client_secret, encryption_key = _oauth_until_success(
            rest_key, client_secret, encryption_key
        )
        status["oauth"] = True

        values = {
            "SERPAPI_KEY": serpapi_key,
            "KAKAO_REST_API_KEY": rest_key,
            "KAKAO_CLIENT_SECRET": client_secret,
            "KAKAO_TOKEN_ENCRYPTION_KEY": encryption_key,
        }
        print("\nSaving encrypted repository secrets...")
        _save_secrets_with_retry(repository, values)
        status["secrets"] = True

        print("Saving installation state and encrypted refresh token to the repository...")
        _commit_setup_files(status["state_reset"])
        commit_done = True
        status["commit"] = True

        pages_settings = f"https://github.com/{repository}/settings/pages"
        status["pages"] = _pages_enabled(repository)
        if not status["pages"]:
            print(f"\nEnable GitHub Actions as the Pages source if needed: {pages_settings}")
            webbrowser.open(pages_settings)

        answer = input("Send one Kakao My Chatroom verification message now? [Y/n] ").strip()
        if answer.lower() in {"", "y", "yes"}:
            _run_delivery_test(repository)
            status["verification"] = "OK"
            print("\nPTIS setup succeeded. Check KakaoTalk My Chatroom for the test message.")
        else:
            status["verification"] = "SKIPPED"
            print("Setup is saved. Run Kakao Setup Verification from Actions later.")

        status["pages"] = _pages_enabled(repository)
        _print_summary(status, repository)
        return 0
    except KeyboardInterrupt:
        if not commit_done and (state_snapshot is not None or auth_snapshot is not None):
            _rollback_setup_files(state_snapshot, auth_snapshot)
        print("\nPTIS setup cancelled.", file=sys.stderr)
        _print_summary(status, repository)
        return 130
    except (InstallError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        if not commit_done and (state_snapshot is not None or auth_snapshot is not None):
            _rollback_setup_files(state_snapshot, auth_snapshot)
        print(f"PTIS setup failed: {exc}", file=sys.stderr)
        _print_summary(status, repository)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
