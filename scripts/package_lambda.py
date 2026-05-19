#!/usr/bin/env python3
"""
Cross-platform Lambda packaging script.

Usage (from repo root, Git Bash or any shell):
  python scripts/package_lambda.py

Packages all Lambdas:
  - lambdas/ingest/    → lambdas/ingest/ingest.zip
  - lambdas/transform/ → lambdas/transform/transform.zip

Run this before every `terraform apply` that changes Lambda code.
To add a new Lambda, append a LambdaSpec entry to LAMBDA_SPECS.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LambdaSpec:
    name: str                # human label used in log lines
    directory: str           # subdirectory under REPO_ROOT/lambdas/
    source_files: list[str]  # Python files to copy into the zip
    zip_name: str            # output zip filename


LAMBDA_SPECS: list[LambdaSpec] = [
    LambdaSpec(
        name="ingest",
        directory="ingest",
        source_files=["handler.py", "eia_client.py", "models.py"],
        zip_name="ingest.zip",
    ),
    LambdaSpec(
        name="transform",
        directory="transform",
        source_files=["handler.py", "aggregator.py", "models.py"],
        zip_name="transform.zip",
    ),
    LambdaSpec(
        name="api",
        directory="api",
        # Nested paths are supported — parent directories are created automatically.
        source_files=[
            "handler.py",
            "main.py",
            "exceptions.py",
            "db.py",
            "cache.py",
            "models.py",
            "routers/__init__.py",
            "routers/prices.py",
        ],
        zip_name="api.zip",
    ),
]


def _clean_dist(dist_dir: Path) -> None:
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True)
    print(f"[package] Cleaned {dist_dir}")


def _install_dependencies(requirements: Path, dist_dir: Path) -> None:
    # Target the Lambda runtime: Python 3.12 on Amazon Linux (manylinux2014 x86_64).
    # This downloads the correct Linux binary wheels regardless of the local OS/Python version.
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--requirement", str(requirements),
        "--target", str(dist_dir),
        "--upgrade",
        "--quiet",
        "--platform", "manylinux2014_x86_64",
        "--python-version", "3.12",
        "--implementation", "cp",
        "--only-binary=:all:",
    ]
    print("[package] Installing dependencies (targeting Python 3.12 / Amazon Linux)...")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print("[package] ERROR: pip install failed.", file=sys.stderr)
        sys.exit(1)
    print("[package] Dependencies installed.")


def _copy_source_files(source_dir: Path, files: list[str], dist_dir: Path) -> None:
    for name in files:
        src  = source_dir / name
        dest = dist_dir / name
        if not src.exists():
            print(f"[package] ERROR: missing source file: {src}", file=sys.stderr)
            sys.exit(1)
        # Create parent directories for nested files (e.g. routers/prices.py)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"[package] Copied {name}")


def _create_zip(dist_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in dist_dir.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(dist_dir))
                file_count += 1
    size_kb = zip_path.stat().st_size // 1024
    print(f"[package] Created {zip_path.name} ({file_count} files, {size_kb} KB)")


def _package_one(spec: LambdaSpec) -> None:
    lambda_dir = REPO_ROOT / "lambdas" / spec.directory
    dist_dir = lambda_dir / "dist"
    zip_path = lambda_dir / spec.zip_name
    requirements = lambda_dir / "requirements.txt"

    print(f"\n[package] -- Packaging {spec.name} Lambda --------------------")

    if not requirements.exists():
        print(f"[package] ERROR: {requirements} not found.", file=sys.stderr)
        sys.exit(1)

    _clean_dist(dist_dir)
    _install_dependencies(requirements, dist_dir)
    _copy_source_files(lambda_dir, spec.source_files, dist_dir)
    _create_zip(dist_dir, zip_path)


def main() -> None:
    for spec in LAMBDA_SPECS:
        _package_one(spec)
    print("\n[package] All Lambdas packaged. Run `terraform apply -var-file=secrets.tfvars` next.")


if __name__ == "__main__":
    main()
