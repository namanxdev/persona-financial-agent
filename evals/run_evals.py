"""Run every eval case and print a pass/fail table. Exits nonzero on failure.

Usage: python evals/run_evals.py
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.cases import EvalResult, build_cases  # noqa: E402 (path setup must run first)


async def _run_all() -> list[EvalResult]:
    results: list[EvalResult] = []
    for name, run in build_cases():
        try:
            results.append(await run())
        except Exception as exc:  # a case raising is a failure to report, not a crash to hide
            results.append(EvalResult(name, False, f"case raised {type(exc).__name__}: {exc}"))
    return results


def _print_table(results: list[EvalResult]) -> None:
    name_width = max(len(r.name) for r in results) + 2
    print(f"{'CASE':<{name_width}}{'RESULT':<8}DETAIL")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{result.name:<{name_width}}{status:<8}{result.detail}")


def main() -> None:
    results = asyncio.run(_run_all())
    _print_table(results)
    failures = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failures)}/{len(results)} cases passed")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
