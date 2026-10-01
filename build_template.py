"""Build a clean PTIS distribution artifact from the update manifest."""

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / ".ptis" / "update_manifest.json"
DEFAULT_USER_CONFIG = {
    "focus_slot": {"mode": "alternate"},
    "focus_search": {"enabled": False},
    "route_watch": {"enabled": False},
    "route_watches": [],
}


class TemplateBuildError(RuntimeError):
    """Raised when the clean distribution cannot be built safely."""


def _safe_relpath(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise TemplateBuildError("Template manifest contains an invalid path.")
    normalized = value.replace("\\", "/").strip()
    path = Path(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TemplateBuildError(f"Unsafe template path: {value!r}")
    return path


def load_manifest(path: Path = MANIFEST) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateBuildError("Update manifest is unreadable or invalid.") from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise TemplateBuildError("Unsupported update manifest schema.")

    parsed = {}
    for key in ("managed_files", "seed_if_missing", "protected_files"):
        values = payload.get(key, [])
        if not isinstance(values, list):
            raise TemplateBuildError(f"Manifest field {key} must be a list.")
        parsed[key] = [_safe_relpath(value) for value in values]
        if len(parsed[key]) != len(set(parsed[key])):
            raise TemplateBuildError(f"Manifest field {key} contains duplicates.")

    protected = set(parsed["protected_files"])
    overlap = protected.intersection(parsed["managed_files"])
    if overlap:
        raise TemplateBuildError(
            "Protected files overlap managed files: "
            + ", ".join(str(path) for path in sorted(overlap))
        )

    allowed_seed_overlap = {Path("user_config.json")}
    seed_overlap = protected.intersection(parsed["seed_if_missing"])
    if seed_overlap.difference(allowed_seed_overlap):
        raise TemplateBuildError(
            "Only user_config.json may be both protected and seed-if-missing."
        )
    return parsed


def template_files(root: Path = ROOT, manifest: dict | None = None) -> list[Path]:
    manifest = manifest or load_manifest()
    files = sorted(
        set(manifest["managed_files"]) | set(manifest["seed_if_missing"]),
        key=lambda path: path.as_posix(),
    )
    for rel in files:
        source = root / rel
        if not source.is_file():
            raise TemplateBuildError(f"Manifest source file is missing: {rel.as_posix()}")

    forbidden = {
        Path("data/state.json"),
        Path("data/kakao_auth.json"),
    }
    leaked = forbidden.intersection(files)
    if leaked:
        raise TemplateBuildError(
            "Runtime/auth files are not allowed in the clean template: "
            + ", ".join(path.as_posix() for path in sorted(leaked))
        )
    return files


def build_directory(output: Path, root: Path = ROOT) -> list[Path]:
    manifest = load_manifest(root / ".ptis" / "update_manifest.json")
    files = template_files(root=root, manifest=manifest)

    output = output.resolve()
    root = root.resolve()
    if output == root or root in output.parents:
        raise TemplateBuildError("Template output must be outside the source repository.")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    for rel in files:
        source = root / rel
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel == Path("user_config.json"):
            target.write_text(
                json.dumps(DEFAULT_USER_CONFIG, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            shutil.copy2(source, target)
    return files


def build_zip(directory: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    files = sorted(
        (path for path in directory.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(directory).as_posix(),
    )
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            rel = path.relative_to(directory).as_posix()
            info = zipfile.ZipInfo(rel)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    args = parser.parse_args(argv)

    try:
        files = build_directory(args.output)
        print(f"Built clean PTIS template with {len(files)} files: {args.output}")
        if args.zip_path is not None:
            build_zip(args.output, args.zip_path)
            print(f"Built template zip: {args.zip_path}")
        return 0
    except (TemplateBuildError, OSError) as exc:
        print(f"PTIS template build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
