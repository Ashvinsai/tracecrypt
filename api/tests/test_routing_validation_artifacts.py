"""Tests for Task 08B validation artifact integrity and metadata compliance."""

import hashlib
import json
import re
from pathlib import Path

VAL_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "var"
    / "routing-validation"
    / "20260927-clm-qwen3-8b-shadow-001"
)


def test_task08b_validation_manifest_integrity():
    manifest_path = VAL_DIR / "manifest.json"
    assert manifest_path.exists(), f"Manifest missing at {manifest_path}"

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["artifact_class"] == "DECISION_SUPPORT_METADATA"
    assert "NOT blockchain evidence" in manifest["caveat"]
    assert "does not establish wallet attribution" in manifest["caveat"]
    assert manifest["metadata"]["action_catalog_version"] == "1.0.0"
    assert manifest["metadata"]["state_schema_version"] == "1.0.0"
    assert manifest["metrics_summary"]["unsafe_action_execution_rate"] == 0.0

    # Verify sha256 of all files
    files = manifest["files"]
    assert len(files) >= 15

    for rel_path, expected_hash in files.items():
        target_file = VAL_DIR / rel_path
        assert target_file.exists(), f"File {rel_path} declared in manifest but missing on disk"
        with open(target_file, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        assert actual_hash == expected_hash, (
            f"Hash mismatch for {rel_path}: {actual_hash} != {expected_hash}"
        )


def test_task08b_validation_artifacts_contain_no_secrets_or_addresses():
    evm_addr = re.compile(r"0x[a-fA-F0-9]{40}")
    tron_addr = re.compile(r"T[A-Za-z1-9]{33}")
    tx_hash = re.compile(r"0x[a-fA-F0-9]{64}")
    sensitive_tokens = re.compile(r"Bearer|kaggle_key|api[_-]?key", re.IGNORECASE)

    for p in VAL_DIR.rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="ignore")
            assert not evm_addr.findall(text), f"EVM address found in {p.name}"
            assert not tron_addr.findall(text), f"TRON address found in {p.name}"
            assert not tx_hash.findall(text), f"Transaction hash found in {p.name}"
            assert not sensitive_tokens.findall(text), f"Sensitive token pattern found in {p.name}"
