"""Desktop-first application entry point for ChatMPD."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from .cli import main as cli_main
from .runtime import LlamaCppRuntime
from .service import prepare_project_task, run_project_task


def run_local_task(
    workspace: Path,
    task: str,
    *,
    runtime_factory: Callable[[], Any] = LlamaCppRuntime,
    preflight_runner: Callable[..., Any] = prepare_project_task,
    service_runner: Callable[..., Any] = run_project_task,
) -> Any:
    """Run one task and release any model process owned by this invocation."""

    prepared = preflight_runner(Path(workspace), task)
    with runtime_factory() as runtime:
        return service_runner(
            Path(workspace), task, endpoint=runtime.endpoint, prepared=prepared
        )


def dispatch(
    arguments: Sequence[str],
    *,
    cli_runner: Callable[[Sequence[str]], int] | None = None,
    gui_launcher: Callable[[Callable[[Path, str], Any]], None] | None = None,
    universal_launcher: Callable[[], None] | None = None,
) -> int:
    """Route a double-click to the GUI and explicit arguments to the CLI."""

    argv = list(arguments)
    if argv:
        return int((cli_runner or cli_main)(argv))
    if gui_launcher is not None:
        gui_launcher(run_local_task)
        return 0
    if universal_launcher is None:
        from .defaults import build_default_orchestrator
        from .webview_host import launch_webview

        universal_launcher = lambda: launch_webview(build_default_orchestrator())
    universal_launcher()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    return dispatch(arguments)
