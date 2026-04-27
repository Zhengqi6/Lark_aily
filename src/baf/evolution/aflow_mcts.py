"""AFlow-style MCTS over candidate AgentGraphs (DMSAS_Design.md §三.亮点 1).

The Composer's third tier: when risk_tier ∈ {high, critical} we generate
N candidate team graphs in parallel and replay each against historical
holdout cases. Only the highest-scoring candidate is committed as a
new blueprint.

For the MVP we keep the search shallow:
  - "candidates" come from `generator(seed)` (typically the LLM with
    different temperatures or persona prompts)
  - "replay" scores each candidate by `success_rate × team_diversity`
    against the existing AgentRuns history; if no history is available
    we fall back to a heuristic structural score so the search still
    converges on something sensible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..storage.backend import StorageBackend, TableName


@dataclass
class GraphCandidate:
    team: list[dict[str, Any]]
    seed: int = 0
    score: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team,
            "seed": self.seed,
            "score": round(self.score, 3),
            "breakdown": {k: round(v, 3) for k, v in self.breakdown.items()},
            "reasoning": self.reasoning,
        }


class AflowMCTS:
    """Tiny MCTS-flavoured replay scorer.

    Real AFlow does Monte-Carlo Tree Search over code-represented
    workflows; for the demo we approximate the *idea* — sample, score
    against history, keep the best — without the deep tree.
    """

    def __init__(self, storage: StorageBackend, *, n_samples: int = 3):
        self.storage = storage
        self.n_samples = n_samples

    def search(
        self,
        scene_type: str,
        generator: Callable[[int], list[dict[str, Any]]],
        *,
        n_samples: int | None = None,
    ) -> GraphCandidate:
        n = n_samples or self.n_samples
        candidates: list[GraphCandidate] = []
        for i in range(n):
            try:
                team = generator(i)
            except Exception:
                continue
            if not team:
                continue
            cand = self._score(scene_type, team, seed=i)
            candidates.append(cand)
        if not candidates:
            return GraphCandidate(team=[], reasoning="no candidates produced")
        winner = max(candidates, key=lambda c: c.score)
        winner.reasoning = (
            f"MCTS over {len(candidates)} samples; best score {winner.score:.2f}."
        )
        return winner

    # ---- scoring -------------------------------------------------
    def _score(self, scene_type: str, team: list[dict[str, Any]], *, seed: int) -> GraphCandidate:
        history_score = self._history_score(scene_type, team)
        diversity = self._diversity(team)
        size_penalty = self._size_penalty(team)
        composite = 0.55 * history_score + 0.35 * diversity - 0.10 * size_penalty
        return GraphCandidate(
            team=team,
            seed=seed,
            score=composite,
            breakdown={
                "history": history_score,
                "diversity": diversity,
                "size_penalty": size_penalty,
            },
        )

    def _history_score(self, scene_type: str, team: list[dict[str, Any]]) -> float:
        """How often have THIS scene's past Blueprints succeeded with the same role set?"""
        bps = self.storage.list_records(
            TableName.AGENT_BLUEPRINTS, where={"scene_type": scene_type}, limit=200
        )
        if not bps:
            return 0.5  # neutral prior
        proposed_roles = {t.get("role") for t in team}
        best = 0.0
        for bp in bps:
            roles = {t.get("role") for t in (bp.get("team_composition") or [])}
            if not roles:
                continue
            jaccard = len(proposed_roles & roles) / max(1, len(proposed_roles | roles))
            sr = float(bp.get("success_rate") or 0.0)
            best = max(best, jaccard * sr)
        return min(1.0, best)

    @staticmethod
    def _diversity(team: list[dict[str, Any]]) -> float:
        roles = {t.get("role") for t in team}
        return min(1.0, len(roles) / 4.0)  # diminishing returns past 4 roles

    @staticmethod
    def _size_penalty(team: list[dict[str, Any]]) -> float:
        return max(0.0, (len(team) - 5) / 5.0)
