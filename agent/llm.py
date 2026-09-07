"""LLM-backed framing choice, with a deterministic offline fallback.

The LLM's only job is picking a non-factual "stance" token (constructive /
cautious / mixed) used to choose which canned framing sentence opens the
answer. It never sees raw evidence values and cannot introduce a factual
claim -- every number in the final answer is substituted from EvidenceItem
objects by agent/grounding.py, not generated here.

Provider: OpenAI, via the `openai` package, key read from OPENAI_API_KEY at
runtime. With no key configured (this environment has none) or on any
provider error, `choose_framing` falls back to a deterministic rule over the
retrieved metric values, so the whole app runs end-to-end with no network
access. `FramingChoice.mode` records which path actually ran.
"""

import logging
import os
from dataclasses import dataclass
from typing import Literal

from agent.models import PersonaName

logger = logging.getLogger(__name__)

Stance = Literal["constructive", "cautious", "mixed"]
FramingMode = Literal["llm", "deterministic_fallback"]

_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
_STANCES: tuple[Stance, ...] = ("constructive", "cautious", "mixed")


@dataclass(frozen=True)
class FramingChoice:
    stance: Stance
    mode: FramingMode


def choose_framing(persona: PersonaName, sector: str, query: str, signal_values: list[float]) -> FramingChoice:
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            choice = _choose_via_openai(api_key, persona, sector, query, signal_values)
            logger.info("framing chosen via OpenAI (%s): %s", _MODEL, choice.stance)
            return choice
        except Exception as exc:  # network/provider failure -- never block the answer
            logger.warning("OpenAI framing call failed, using deterministic fallback: %s", exc)
    choice = _choose_deterministic(signal_values)
    logger.info("framing chosen via deterministic fallback: %s", choice.stance)
    return choice


def _choose_deterministic(signal_values: list[float]) -> FramingChoice:
    if not signal_values:
        return FramingChoice("mixed", "deterministic_fallback")
    average = sum(signal_values) / len(signal_values)
    if average > 0:
        return FramingChoice("constructive", "deterministic_fallback")
    if average < 0:
        return FramingChoice("cautious", "deterministic_fallback")
    return FramingChoice("mixed", "deterministic_fallback")


def _choose_via_openai(
    api_key: str, persona: PersonaName, sector: str, query: str, signal_values: list[float]
) -> FramingChoice:
    from openai import OpenAI  # deferred import: keeps offline runs dependency-light

    client = OpenAI(api_key=api_key)
    prompt = (
        f"Persona: {persona}. Sector: {sector}. Question: {query!r}. "
        f"Retrieved signal values: {signal_values}. "
        "Reply with exactly one word, no punctuation: constructive, cautious, or mixed."
    )
    response = client.chat.completions.create(
        model=_MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=5, temperature=0,
    )
    token = (response.choices[0].message.content or "").strip().lower()
    if token not in _STANCES:
        raise ValueError(f"unexpected framing token from model: {token!r}")
    return FramingChoice(token, "llm")  # type: ignore[arg-type]
