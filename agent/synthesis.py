"""Constrained, evidence-backed synthesis: the model writes, a validator decides.

The model is given the EvidenceItem rows retrieved this turn -- already rendered
to display strings by agent/evidence_guard.py -- plus the persona's policy, and
must return one strict JSON object: thesis, supporting_points, risks,
limitations, and the evidence_ids it relied on. None of it is trusted on return:

  * every evidence_id must be one actually retrieved this turn,
  * every ticker-shaped token in the prose must belong to a cited company,
  * every numeric token in the prose must appear verbatim in a display value or
    as_of_date the model was handed -- so it may quote a figure but cannot
    compute, restate, round, or invent one.

A candidate that fails any check is discarded and agent/grounding.py composes
the answer instead -- the same path taken when no key is configured or the
provider errors. The grounding guarantee therefore rests on the validator, not
on the model following instructions.

Set `AGENT_SYNTHESIS=off` to force the deterministic composer even with a key
configured, which is what makes a run reproducible.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable

from agent.evidence_guard import evidence_payload, out_of_scope_mentions, validate
from agent.models import CompanyRow, EvidenceItem, PersonaName, Synthesis
from agent.personas import PersonaPolicy

logger = logging.getLogger(__name__)

_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
_MAX_ITEMS = 6


@dataclass(frozen=True)
class SynthesisResult:
    """A validated draft, or nothing -- plus why, when the reason is actionable.

    `out_of_scope` carries company names the draft used that the sector catalog
    does not contain. The draft itself is discarded either way; the names are
    kept because they tell the caller something the query alone did not.
    """

    synthesis: Synthesis | None
    out_of_scope: tuple[str, ...] = ()


def render(candidate: Synthesis) -> str:
    """Flatten a validated synthesis into the `answer` string."""
    parts = [candidate.thesis.strip()]
    for label, items in (
        ("Supporting evidence", candidate.supporting_points),
        ("Risks", candidate.risks),
        ("Limitations", candidate.limitations),
    ):
        if items:
            parts.append(f"{label}: " + " ".join(item.strip() for item in items))
    return " ".join(parts)


def build_prompt(
    persona: PersonaName,
    sector: str,
    query: str,
    policy: PersonaPolicy,
    payload: list[dict[str, str]],
    stance: str,
) -> str:
    return (
        f"You are a {persona.replace('_', ' ')} answering a question about the {sector} sector.\n"
        f"Question: {query!r}\n"
        f"Your screening approach this turn: {policy.ranking_rationale}\n"
        f"Overall stance to take: {stance}.\n\n"
        f"Evidence retrieved this turn (the ONLY facts you may use):\n{json.dumps(payload, indent=1)}\n\n"
        "Write an investment thesis grounded exclusively in that evidence. These rules are\n"
        "enforced by a validator that discards your whole answer on any violation:\n"
        "1. Copy every figure EXACTLY as it appears in a 'display' or 'as_of_date' value.\n"
        "   Never compute, sum, average, round, or restate a number in another form.\n"
        "2. Name companies only by tickers present in the evidence.\n"
        "3. List in evidence_ids every evidence row you drew on, and no others.\n"
        "4. The qualitative judgement is yours; the numbers are not.\n"
        "5. Never name a company that is not in the evidence above, even if the question\n"
        "   asks about one. You hold no data on it, so you cannot discuss it at all.\n\n"
        'Reply with JSON only: {"thesis": str, "supporting_points": [str], "risks": [str],\n'
        ' "limitations": [str], "evidence_ids": [str]}. Keep the thesis to two sentences and\n'
        f" each list to at most {_MAX_ITEMS} short entries."
    )


def _complete_via_openai(api_key: str, prompt: str) -> str:
    from openai import OpenAI  # deferred import: keeps offline runs dependency-light

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=700,
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def synthesize(
    persona: PersonaName,
    sector: str,
    query: str,
    policy: PersonaPolicy,
    evidence: list[EvidenceItem],
    stance: str,
    catalog: list[CompanyRow] | None = None,
    complete: Callable[[str], str] | None = None,
) -> SynthesisResult:
    """Return a validated draft, or an empty result to fall back to deterministic composition.

    `complete` is injectable so the path can be exercised against fixed model
    output without a provider call.
    """
    if not evidence:
        return SynthesisResult(None)
    if os.environ.get("AGENT_SYNTHESIS", "on").strip().lower() == "off":
        return SynthesisResult(None)
    if complete is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return SynthesisResult(None)

        def complete(prompt: str) -> str:
            return _complete_via_openai(api_key, prompt)

    try:
        raw = complete(build_prompt(persona, sector, query, policy, evidence_payload(evidence), stance))
        candidate = Synthesis.model_validate_json(raw)
    except Exception as exc:  # provider, transport, or schema failure
        logger.warning("synthesis unavailable, using deterministic composer: %s", exc)
        return SynthesisResult(None)

    reason = validate(candidate, evidence, catalog)
    if reason is not None:
        logger.warning("synthesis rejected, using deterministic composer: %s", reason)
        outside = tuple(out_of_scope_mentions(candidate, catalog)) if catalog is not None else ()
        return SynthesisResult(None, outside)
    logger.info("synthesis accepted (%s), citing %d evidence rows", _MODEL, len(candidate.evidence_ids))
    return SynthesisResult(candidate)
