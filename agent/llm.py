"""LLM-backed framing choice, with a deterministic offline fallback.

The LLM's only job here is picking a non-factual "stance" token (constructive /
cautious / mixed) used to choose which canned framing sentence opens the
answer. It is shown the retrieved values as labeled strings ("ORCL
free_cash_flow_ttm=-24540000000.0") so it has something to judge, but it cannot
introduce a factual claim: its reply is one of a fixed set of words, and every
number in the final answer is substituted from EvidenceItem objects by
agent/grounding.py, not generated here.

Provider: OpenAI, via the `openai` package, key read from OPENAI_API_KEY at
runtime. With no key configured or on any provider error, `choose_framing`
returns "neutral" -- the answer then opens without claiming any stance at all.
`FramingChoice.mode` records which path actually ran.
"""

import logging
import os
from dataclasses import dataclass
from typing import Literal

from agent.models import PersonaName

logger = logging.getLogger(__name__)

Stance = Literal["constructive", "cautious", "mixed", "neutral"]
FramingMode = Literal["llm", "deterministic_fallback"]

_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
_MODEL_STANCES: tuple[Stance, ...] = ("constructive", "cautious", "mixed")


@dataclass(frozen=True)
class FramingChoice:
    stance: Stance
    mode: FramingMode


def choose_framing(persona: PersonaName, sector: str, query: str, signals: list[str]) -> FramingChoice:
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        try:
            choice = _choose_via_openai(api_key, persona, sector, query, signals)
            logger.info("framing chosen via OpenAI (%s): %s", _MODEL, choice.stance)
            return choice
        except Exception as exc:  # network/provider failure -- never block the answer
            logger.warning("OpenAI framing call failed, using deterministic fallback: %s", exc)
    choice = _choose_deterministic()
    logger.info("framing chosen via deterministic fallback: %s", choice.stance)
    return choice


def _choose_deterministic() -> FramingChoice:
    """Always neutral: there is no honest keyless rule for a stance.

    The retrieved values mix units -- FCF in dollars, P/E as a multiple, margins
    as ratios, headcounts as people -- so any average or vote across them is
    dominated by whichever number is largest, and its sign says nothing about
    the question. A fixed rule would claim a stance it never actually read.
    """
    return FramingChoice("neutral", "deterministic_fallback")


def _choose_via_openai(
    api_key: str, persona: PersonaName, sector: str, query: str, signals: list[str]
) -> FramingChoice:
    from openai import OpenAI  # deferred import: keeps offline runs dependency-light

    # The SDK default is a 600 s read timeout with 2 retries: far too long to hold a
    # request open for a one-word reply that has a deterministic fallback.
    client = OpenAI(api_key=api_key, timeout=20.0, max_retries=1)
    prompt = (
        f"Persona: {persona}. Sector: {sector}. Question: {query!r}. "
        f"Retrieved signals (company metric=value): {signals}. "
        "Reply with exactly one word, no punctuation: constructive, cautious, or mixed."
    )
    response = client.chat.completions.create(
        model=_MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=5, temperature=0,
    )
    token = (response.choices[0].message.content or "").strip().lower()
    if token not in _MODEL_STANCES:
        raise ValueError(f"unexpected framing token from model: {token!r}")
    return FramingChoice(token, "llm")  # type: ignore[arg-type]
