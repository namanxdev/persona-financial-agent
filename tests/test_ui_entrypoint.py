"""The Streamlit entry point must load under the sys.path `streamlit run` actually gives it."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_entry_point_resolves_the_agent_package() -> None:
    """Reproduce Streamlit's loader: only ui/ on sys.path, repo root absent.

    `streamlit.web.bootstrap._fix_sys_path` inserts the script's own folder and nothing
    else, and this project is not installed into the environment, so ui/app.py has to put
    the repo root on sys.path itself. `-I` reproduces that (no CWD entry, no PYTHONPATH)
    and a foreign cwd proves the fix does not depend on being launched from the root.
    `run_name` is not "__main__", so module-level imports run but `main()` does not.
    """
    program = (
        "import runpy, sys; "
        f"sys.path.insert(0, {str(ROOT / 'ui')!r}); "
        f"runpy.run_path({str(ROOT / 'ui' / 'app.py')!r}, run_name='streamlit_import_check')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", program],
        capture_output=True,
        text=True,
        cwd=ROOT.parent,
    )
    assert result.returncode == 0, result.stderr
