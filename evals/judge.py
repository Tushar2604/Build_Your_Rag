"""LLM-as-judge for the subjective quality axes.

Two scores the deterministic metrics can't capture:

  * faithfulness    — is every claim in the answer supported by the retrieved
                      context? (catches hallucination / ungrounded generation)
  * answer_relevance — does the answer actually address the question asked?

Both are scored 0.0–1.0 by an LLM through the existing `LLMProvider` port, so the
judge reuses the Groq/Gemini failover already wired in the container — no new
provider integration. We deliberately judge with a *separate* call (and ideally a
different model than the one under test) to avoid a model grading its own output.

Failure modes handled explicitly, because an LLM judge is itself an unreliable
system: the model may wrap JSON in prose, emit markdown fences, or return an
out-of-range score. `_parse_score` is defensive about all three and the judge
degrades to a recorded `error` rather than crashing a run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import structlog
from src.application.ports.services import LLMProvider

log = structlog.get_logger(__name__)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

_FAITHFULNESS_SYSTEM = (
    "You are a strict evaluator of factual grounding. You will be given CONTEXT "
    "and an ANSWER. Decide whether EVERY factual claim in the ANSWER is directly "
    "supported by the CONTEXT. Unsupported or contradicted claims lower the score. "
    "An answer that correctly says the information is not available is fully "
    "faithful. Respond ONLY with a JSON object: "
    '{"score": <float 0..1>, "reason": "<one sentence>"}.'
)

_RELEVANCE_SYSTEM = (
    "You are a strict evaluator of answer relevance. You will be given a QUESTION "
    "and an ANSWER. Decide how well the ANSWER addresses the QUESTION, ignoring "
    "whether it is factually correct. Respond ONLY with a JSON object: "
    '{"score": <float 0..1>, "reason": "<one sentence>"}.'
)


@dataclass(frozen=True)
class JudgeScore:
    score: float  # clamped to [0, 1]; 0.0 when the judge errored
    reason: str
    ok: bool = True  # False when the judge call/parse failed (excluded from means)


def _parse_score(raw: str) -> tuple[float, str]:
    """Extract {"score", "reason"} from a possibly-noisy model response.

    Tolerates leading prose and ```json fences by locating the first balanced-ish
    object. Raises ValueError if nothing parseable is found so the caller can
    record an explicit judge failure.
    """
    match = _JSON_OBJECT.search(raw)
    if not match:
        raise ValueError(f"no JSON object in judge output: {raw[:120]!r}")
    data = json.loads(match.group(0))
    score = float(data["score"])
    if not 0.0 <= score <= 1.0:
        # Some models answer on a 1–5 or 0–100 scale despite instructions.
        score = max(0.0, min(1.0, score / 100.0 if score > 5 else score / 5.0))
    return score, str(data.get("reason", "")).strip()


class LLMJudge:
    """Scores faithfulness and relevance via an `LLMProvider`."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def _judge(self, system: str, user: str, axis: str) -> JudgeScore:
        try:
            result = await self._llm.generate(system, user)
            score, reason = _parse_score(result.text)
            return JudgeScore(score=score, reason=reason)
        except Exception as exc:  # noqa: BLE001 - a judge failure must not abort the run
            log.warning("judge.failed", axis=axis, error=str(exc))
            return JudgeScore(score=0.0, reason=f"judge error: {exc}", ok=False)

    async def faithfulness(self, context: str, answer: str) -> JudgeScore:
        user = f"CONTEXT:\n{context}\n\nANSWER:\n{answer}"
        return await self._judge(_FAITHFULNESS_SYSTEM, user, axis="faithfulness")

    async def answer_relevance(self, question: str, answer: str) -> JudgeScore:
        user = f"QUESTION:\n{question}\n\nANSWER:\n{answer}"
        return await self._judge(_RELEVANCE_SYSTEM, user, axis="answer_relevance")
