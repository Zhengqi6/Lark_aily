"""Regression test for Scene Router accuracy.

Runs the 20 fixture cases through the real LLM (zhizengzeng relay) and
asserts accuracy is ≥85% as required by PRD §10.1.

Skipped automatically if LLM_API_KEY isn't available.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from baf.agents.base import RunContext
from baf.agents.scene_router import SceneRouterAgent
from baf.config import Config
from baf.llm.client import LLMClient
from baf.storage.mock_backend import MockBackend

FIX = Path(__file__).parent / "fixtures" / "cases.jsonl"


def _load_cases():
    with FIX.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


@pytest.mark.skipif(
    not os.environ.get("LLM_API_KEY") and not (Path.home() / ".baf/config.json").exists(),
    reason="No LLM_API_KEY configured",
)
def test_scene_router_accuracy(tmp_path):
    cfg = Config.load()
    llm = LLMClient(cfg)
    # isolate mock dir so we don't touch the user's data
    import baf.config as config_mod
    config_mod.MOCK_DIR = tmp_path
    storage = MockBackend(root=tmp_path)
    storage.ensure_tables()

    router = SceneRouterAgent(llm, storage)
    cases = list(_load_cases())
    correct = 0
    wrong = []
    for case in cases:
        ctx = RunContext(
            case_id="T",
            case_record_id="T",
            description=case["desc"],
        )
        res = router.run(ctx)
        got = res.output.get("scene_type")
        if got == case["expected"]:
            correct += 1
        else:
            wrong.append((case["desc"][:40], case["expected"], got))

    accuracy = correct / len(cases)
    print(f"\nScene Router accuracy: {accuracy:.2%}  ({correct}/{len(cases)})")
    for desc, exp, got in wrong:
        print(f"  ✗ {desc}… expected={exp}  got={got}")
    assert accuracy >= 0.85, f"accuracy {accuracy:.2%} < 85%"
