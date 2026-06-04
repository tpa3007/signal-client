"""Integrity helpers for the public Signal client artifact."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


DEFAULT_PROTECTED_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    "INSTRUCTIONS.md",
    "TERMS.md",
    "run_client_audit.py",
    "run_signal_machine.py",
    "client_policy.py",
    "rules.json",
    "signal_client",
)


def _iter_files(root: Path, protected_paths: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for raw in protected_paths:
        path = root / raw
        if not path.exists():
            continue
        if path.is_file():
            files.append(path)
        else:
            files.extend(
                p for p in path.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
            )
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root: Path, protected_paths: Iterable[str] = DEFAULT_PROTECTED_PATHS) -> dict:
    root = root.resolve()
    files = []
    for path in _iter_files(root, protected_paths):
        rel = path.relative_to(root).as_posix()
        files.append({"path": rel, "sha256": file_sha256(path)})
    aggregate = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "signal-client-integrity-v1",
        "protected_paths": list(protected_paths),
        "aggregate_sha256": aggregate,
        "files": files,
    }


def write_lock(root: Path, lock_name: str = "INTEGRITY.lock") -> dict:
    manifest = build_manifest(root)
    (root / lock_name).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_lock(root: Path, lock_name: str = "INTEGRITY.lock") -> dict:
    root = root.resolve()
    lock_path = root / lock_name
    if not lock_path.exists():
        return {"ok": False, "error": "missing_integrity_lock", "changed": [], "missing": []}

    expected = json.loads(lock_path.read_text(encoding="utf-8"))
    current = build_manifest(root, expected.get("protected_paths") or DEFAULT_PROTECTED_PATHS)
    expected_files = {item["path"]: item["sha256"] for item in expected.get("files", [])}
    current_files = {item["path"]: item["sha256"] for item in current.get("files", [])}

    missing = sorted(set(expected_files) - set(current_files))
    added = sorted(set(current_files) - set(expected_files))
    changed = sorted(
        path for path in set(expected_files) & set(current_files)
        if expected_files[path] != current_files[path]
    )
    ok = (
        expected.get("aggregate_sha256") == current.get("aggregate_sha256")
        and not missing
        and not added
        and not changed
    )
    return {
        "ok": ok,
        "expected_aggregate_sha256": expected.get("aggregate_sha256"),
        "current_aggregate_sha256": current.get("aggregate_sha256"),
        "missing": missing,
        "added": added,
        "changed": changed,
    }
