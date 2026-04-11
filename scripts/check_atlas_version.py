from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _normalize_tag(tag: str) -> str:
    value = tag.strip()
    if value.startswith("refs/tags/"):
        value = value.removeprefix("refs/tags/")
    return value


def _load_versions(repo_root: Path) -> dict[str, str]:
    package_json = json.loads((repo_root / "apps" / "atlas" / "package.json").read_text(encoding="utf-8"))
    tauri_conf = json.loads(
        (repo_root / "apps" / "atlas" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    cargo_toml = tomllib.loads((repo_root / "apps" / "atlas" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        "package.json": str(package_json["version"]).strip(),
        "tauri.conf.json": str(tauri_conf["version"]).strip(),
        "Cargo.toml": str(cargo_toml["package"]["version"]).strip(),
        "pyproject.toml": str(pyproject["project"]["version"]).strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Atlas version consistency across manifests.")
    parser.add_argument("--tag", help="Optional git tag to validate, expected format vX.Y.Z")
    args = parser.parse_args()

    versions = _load_versions(_repo_root())
    unique_versions = sorted(set(versions.values()))
    if len(unique_versions) != 1:
        details = ", ".join(f"{path}={value}" for path, value in versions.items())
        raise SystemExit(f"Atlas version mismatch across manifests: {details}")

    version = unique_versions[0]
    if args.tag:
        normalized_tag = _normalize_tag(args.tag)
        expected_tag = f"v{version}"
        if normalized_tag != expected_tag:
            raise SystemExit(f"Git tag {normalized_tag!r} does not match manifest version {expected_tag!r}.")

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
