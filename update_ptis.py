"""Safely update an installed PTIS repository from the upstream source."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_UPSTREAM = os.environ.get(
    "PTIS_UPSTREAM_URL",
    "https://github.com/kijm32-ops/flight-bot.git",
)
DEFAULT_BRANCH = os.environ.get("PTIS_UPSTREAM_BRANCH", "main")
VERSION_FILE = "PTIS_VERSION"
MANIFEST_FILE = ".ptis/update_manifest.json"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class UpdateError(RuntimeError):
    """Raised when an installed PTIS repository cannot be updated safely."""


def _run(args, *, cwd: Path, capture=True, check=True):
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=capture,
        check=check,
    )


def _repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    result = _run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
    )
    return Path(result.stdout.strip()).resolve()


def _parse_version(value: str):
    text = value.strip()
    match = VERSION_RE.fullmatch(text)
    if not match:
        raise UpdateError(
            f"Unsupported PTIS version {text!r}; expected MAJOR.MINOR.PATCH."
        )
    return tuple(int(part) for part in match.groups())


def _local_version(root: Path):
    path = root / VERSION_FILE
    if not path.exists():
        return (0, 0, 0), "legacy"
    text = path.read_text(encoding="utf-8").strip()
    return _parse_version(text), text


def _ensure_clean(root: Path) -> None:
    result = _run(["git", "status", "--porcelain"], cwd=root)
    if result.stdout.strip():
        raise UpdateError(
            "Working tree is not clean. Commit/stash local changes before applying a PTIS update."
        )


def _fetch_snapshot(root: Path, upstream: str, branch: str) -> str:
    try:
        _run(
            ["git", "fetch", "--quiet", "--no-tags", upstream, branch],
            cwd=root,
        )
        result = _run(["git", "rev-parse", "FETCH_HEAD"], cwd=root)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise UpdateError(
            "Could not fetch the PTIS upstream snapshot."
            + (f" {detail}" if detail else "")
        ) from exc
    sha = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise UpdateError("Fetched upstream did not resolve to a commit SHA.")
    return sha


def _show_text(root: Path, sha: str, path: str) -> str:
    try:
        result = _run(["git", "show", f"{sha}:{path}"], cwd=root)
    except subprocess.CalledProcessError as exc:
        raise UpdateError(
            f"Upstream snapshot is missing required file: {path}"
        ) from exc
    return result.stdout


def _safe_relpath(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UpdateError("Update manifest contains an invalid path.")
    path = value.replace("\\", "/").strip()
    parts = path.split("/")
    if path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise UpdateError(f"Unsafe update manifest path: {value!r}")
    return path


def _manifest(root: Path, sha: str) -> dict:
    try:
        payload = json.loads(_show_text(root, sha, MANIFEST_FILE))
    except json.JSONDecodeError as exc:
        raise UpdateError("Upstream update manifest is invalid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise UpdateError("Unsupported PTIS update manifest schema.")

    parsed = {}
    for key in (
        "managed_files",
        "seed_if_missing",
        "protected_files",
        "remove_files",
    ):
        values = payload.get(key, [])
        if not isinstance(values, list):
            raise UpdateError(f"Update manifest field {key} must be a list.")
        parsed[key] = [_safe_relpath(value) for value in values]
        if len(parsed[key]) != len(set(parsed[key])):
            raise UpdateError(f"Update manifest field {key} contains duplicates.")

    protected = set(parsed["protected_files"])
    for key in ("managed_files", "remove_files"):
        overlap = protected.intersection(parsed[key])
        if overlap:
            raise UpdateError(
                "Update manifest attempts to modify protected files: "
                + ", ".join(sorted(overlap))
            )

    seed_overlap = protected.intersection(parsed["seed_if_missing"])
    allowed_seed = {"user_config.json"}
    if seed_overlap.difference(allowed_seed):
        raise UpdateError(
            "Only user_config.json may be protected and seed-if-missing."
        )
    return parsed


def _validate_snapshot_files(root: Path, sha: str, manifest: dict) -> None:
    required = set(manifest["managed_files"]) | set(manifest["seed_if_missing"])
    for path in sorted(required):
        try:
            _run(
                ["git", "cat-file", "-e", f"{sha}:{path}"],
                cwd=root,
            )
        except subprocess.CalledProcessError as exc:
            raise UpdateError(
                f"Update manifest references a missing upstream file: {path}"
            ) from exc


def inspect_update(root: Path, upstream: str, branch: str) -> dict:
    sha = _fetch_snapshot(root, upstream, branch)
    upstream_text = _show_text(root, sha, VERSION_FILE).strip()
    upstream_version = _parse_version(upstream_text)
    local_version, local_text = _local_version(root)
    manifest = _manifest(root, sha)
    _validate_snapshot_files(root, sha, manifest)
    return {
        "sha": sha,
        "local_version": local_version,
        "local_text": local_text,
        "upstream_version": upstream_version,
        "upstream_text": upstream_text,
        "manifest": manifest,
        "available": upstream_version > local_version,
    }


def _checkout_path(root: Path, sha: str, path: str) -> None:
    _run(["git", "checkout", sha, "--", path], cwd=root)


def apply_update(root: Path, info: dict) -> list[str]:
    _ensure_clean(root)
    if not info["available"]:
        return []

    manifest = info["manifest"]
    changed_paths = []
    try:
        for path in manifest["managed_files"]:
            _checkout_path(root, info["sha"], path)
            changed_paths.append(path)

        for path in manifest["seed_if_missing"]:
            target = root / path
            if not target.exists():
                _checkout_path(root, info["sha"], path)
                changed_paths.append(path)

        for path in manifest["remove_files"]:
            result = _run(
                ["git", "rm", "--ignore-unmatch", "--", path],
                cwd=root,
                check=False,
            )
            if result.returncode not in (0, 1):
                raise UpdateError(f"Could not remove obsolete managed file: {path}")
            if result.returncode == 0:
                changed_paths.append(path)
    except Exception:
        _run(["git", "reset", "--hard", "HEAD"], cwd=root, check=False)
        raise

    return changed_paths


def _print_plan(info: dict) -> None:
    print(f"PTIS installed version: {info['local_text']}")
    print(f"PTIS upstream version:  {info['upstream_text']}")
    print(f"Upstream snapshot:      {info['sha']}")
    if info["available"]:
        print("Update available.")
    else:
        print("No newer PTIS version is available.")
    protected = info["manifest"]["protected_files"]
    print("Protected user files:")
    for path in protected:
        print(f"  - {path}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check",
        action="store_true",
        help="Fetch upstream metadata and report whether an update is available.",
    )
    action.add_argument(
        "--apply",
        action="store_true",
        help="Apply the newer upstream managed files to a clean working tree.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation for --apply.",
    )
    parser.add_argument(
        "--upstream",
        default=DEFAULT_UPSTREAM,
        help="PTIS upstream Git repository URL/path.",
    )
    parser.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help="PTIS upstream branch.",
    )
    args = parser.parse_args(argv)

    try:
        root = _repo_root()
        info = inspect_update(root, args.upstream, args.branch)
        _print_plan(info)

        if not args.apply:
            return 0
        if not info["available"]:
            return 0

        if not args.yes:
            answer = input(
                "Apply managed PTIS files now? Existing protected files will be kept. [y/N] "
            ).strip().lower()
            if answer not in {"y", "yes"}:
                print("Update cancelled before changing files.")
                return 0

        changed = apply_update(root, info)
        if changed:
            print(
                f"Applied PTIS {info['upstream_text']} managed files. "
                "Review the Git diff before committing."
            )
            for path in sorted(set(changed)):
                print(f"  updated: {path}")
        else:
            print("No file changes were required.")
        return 0
    except (UpdateError, OSError, subprocess.CalledProcessError) as exc:
        print(f"PTIS update failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
