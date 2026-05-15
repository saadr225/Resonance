from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_gitlab_ci_is_used_instead_of_github_actions() -> None:
    assert (ROOT / ".gitlab-ci.yml").exists()
    assert not (ROOT / ".github" / "workflows").exists()


def test_shared_proto_exists() -> None:
    proto = ROOT / "proto" / "resonance.proto"

    assert proto.exists()
    assert "service AudioProcessor" in proto.read_text(encoding="utf-8")
