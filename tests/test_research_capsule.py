import io
import json
import zipfile

import pytest

from research_engine.research_capsule import (
    CapsuleArtifact,
    build_capsule,
    verify_capsule_bytes,
    verify_capsule_file,
    write_capsule,
)


def _artifacts():
    return [
        CapsuleArtifact("source", "sources/paper.txt", b"source text", "text/plain", ("SRC1",)),
        CapsuleArtifact("code", "code/test.py", b"print('ok')\n", "text/x-python", ("COMMIT1",)),
        CapsuleArtifact("result", "results/metrics.json", b'{"score":1.2}', "application/json", ("RUN1",)),
    ]


def test_same_inputs_produce_identical_capsule_bytes_and_id():
    one = build_capsule(_artifacts(), environment={"python": "3.11"}, metadata={"question": "Q"})
    two = build_capsule(list(reversed(_artifacts())), environment={"python": "3.11"}, metadata={"question": "Q"})
    assert one.capsule_id == two.capsule_id
    assert one.capsule_sha256 == two.capsule_sha256
    assert one.bytes_data == two.bytes_data
    verified = verify_capsule_bytes(one.bytes_data)
    assert verified.valid is True
    assert verified.capsule_id == one.capsule_id
    assert verified.artifact_count == 3


def test_capsule_roundtrip_to_file_verifies(tmp_path):
    capsule = build_capsule(_artifacts(), environment={"lockfile": "abc"})
    path = write_capsule(str(tmp_path / "research.zip"), capsule)
    result = verify_capsule_file(path)
    assert result.valid is True
    assert result.capsule_id == capsule.capsule_id


def test_artifact_tampering_is_detected():
    capsule = build_capsule(_artifacts(), environment={})
    original = zipfile.ZipFile(io.BytesIO(capsule.bytes_data), "r")
    entries = {name: original.read(name) for name in original.namelist()}
    original.close()
    entries["results/metrics.json"] = b'{"score":999}'
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    result = verify_capsule_bytes(output.getvalue())
    assert result.valid is False
    assert any("hash mismatch" in error for error in result.errors)


def test_manifest_goalpost_tampering_is_detected_even_if_artifacts_unchanged():
    capsule = build_capsule(_artifacts(), environment={})
    original = zipfile.ZipFile(io.BytesIO(capsule.bytes_data), "r")
    entries = {name: original.read(name) for name in original.namelist()}
    original.close()
    manifest = json.loads(entries["manifest.json"])
    manifest["metadata"]["post_hoc"] = True
    entries["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    result = verify_capsule_bytes(output.getvalue())
    assert result.valid is False
    assert "capsule_id does not match canonical manifest" in result.errors


def test_undeclared_file_is_detected():
    capsule = build_capsule(_artifacts(), environment={})
    original = zipfile.ZipFile(io.BytesIO(capsule.bytes_data), "r")
    entries = {name: original.read(name) for name in original.namelist()}
    original.close()
    entries["extra/hidden.txt"] = b"not declared"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    result = verify_capsule_bytes(output.getvalue())
    assert result.valid is False
    assert any("undeclared" in error for error in result.errors)


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "a/../secret",
        ".env",
        "nested/.env",
        "keys/api_key.txt",
        "keys/client-secret.json",
        "keys/access_token.txt",
        "keys/refresh-token.json",
        "keys/password.txt",
        "private_key.pem",
        "/etc/passwd",
        "C:/Users/test/secret.txt",
        "manifest.json",
        "MANIFEST.JSON",
    ],
)
def test_unsafe_or_secret_like_paths_are_rejected(path):
    with pytest.raises(ValueError):
        build_capsule([CapsuleArtifact("data", path, b"x")], environment={})


def test_normal_non_secret_names_are_not_overblocked():
    capsule = build_capsule(
        [
            CapsuleArtifact("data", "analysis/tokenization_metrics.csv", b"x"),
            CapsuleArtifact("source", "docs/keyboard_notes.txt", b"y"),
        ],
        environment={},
    )
    assert verify_capsule_bytes(capsule.bytes_data).valid is True


def test_case_colliding_paths_fail_closed():
    with pytest.raises(ValueError, match="case-colliding"):
        build_capsule(
            [
                CapsuleArtifact("data", "data/X.csv", b"a"),
                CapsuleArtifact("data", "data/x.csv", b"b"),
            ],
            environment={},
        )


def test_duplicate_paths_and_unknown_kinds_fail_closed():
    with pytest.raises(ValueError, match="duplicate"):
        build_capsule([
            CapsuleArtifact("data", "data/x.csv", b"a"),
            CapsuleArtifact("data", "data/x.csv", b"b"),
        ], environment={})
    with pytest.raises(ValueError, match="unsupported"):
        build_capsule([CapsuleArtifact("mystery", "x.bin", b"x")], environment={})


def test_invalid_or_empty_payload_is_not_verified():
    assert verify_capsule_bytes(b"").valid is False
    assert verify_capsule_bytes(b"not-a-zip").valid is False
