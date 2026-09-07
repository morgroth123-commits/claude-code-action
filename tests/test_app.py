from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace


class _FakeRuntime:
    endpoint = "http://127.0.0.1:9090"

    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self) -> "_FakeRuntime":
        self.entered = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self.exited = True


class ApplicationDispatchTest(unittest.TestCase):
    def test_no_arguments_launches_the_desktop_ui_with_the_local_task_runner(self) -> None:
        from chatmpd.app import dispatch

        launched: list[object] = []

        result = dispatch(
            [],
            cli_runner=lambda unused: self.fail("CLI must not run on double-click"),
            gui_launcher=launched.append,
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(launched), 1)
        self.assertTrue(callable(launched[0]))

    def test_production_no_argument_path_can_launch_the_universal_front_door(self) -> None:
        from chatmpd.app import dispatch

        launched: list[str] = []
        result = dispatch([], universal_launcher=lambda: launched.append("universal"))

        self.assertEqual(result, 0)
        self.assertEqual(launched, ["universal"])

    def test_arguments_are_forwarded_to_the_cli_without_opening_a_window(self) -> None:
        from chatmpd.app import dispatch

        received: list[list[str]] = []

        result = dispatch(
            ["doctor"],
            cli_runner=lambda arguments: received.append(arguments) or 3,
            gui_launcher=lambda unused: self.fail("GUI must not open for CLI commands"),
        )

        self.assertEqual(result, 3)
        self.assertEqual(received, [["doctor"]])

    def test_local_task_runner_starts_and_always_stops_its_owned_runtime(self) -> None:
        from chatmpd.app import run_local_task

        runtime = _FakeRuntime()
        calls: list[tuple[Path, str, str]] = []
        expected = SimpleNamespace(result=SimpleNamespace(status="succeeded"))
        expected_prepared = object()
        preflight_finished = False

        def preflight(workspace: Path, task: str) -> object:
            nonlocal preflight_finished
            self.assertEqual((workspace, task), (Path("C:/project"), "Repair it"))
            preflight_finished = True
            return expected_prepared

        def runtime_factory() -> _FakeRuntime:
            self.assertTrue(preflight_finished)
            return runtime

        outcome = run_local_task(
            Path("C:/project"),
            "Repair it",
            runtime_factory=runtime_factory,
            preflight_runner=preflight,
            service_runner=lambda workspace, task, *, endpoint, prepared: (
                self.assertIs(prepared, expected_prepared)
                or
                calls.append((workspace, task, endpoint)) or expected
            ),
        )

        self.assertIs(outcome, expected)
        self.assertTrue(runtime.entered)
        self.assertTrue(runtime.exited)
        self.assertEqual(
            calls,
            [(Path("C:/project"), "Repair it", "http://127.0.0.1:9090")],
        )

    def test_local_task_runner_stops_the_runtime_when_the_task_fails(self) -> None:
        from chatmpd.app import run_local_task

        runtime = _FakeRuntime()

        def fail(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("model failed")

        with self.assertRaisesRegex(RuntimeError, "model failed"):
            run_local_task(
                Path("C:/project"),
                "Repair it",
                runtime_factory=lambda: runtime,
                preflight_runner=lambda unused_workspace, unused_task: object(),
                service_runner=fail,
            )

        self.assertTrue(runtime.exited)

    def test_failed_preflight_never_constructs_or_loads_the_model_runtime(self) -> None:
        from chatmpd.app import run_local_task

        def forbidden_runtime() -> object:
            self.fail("runtime must not be constructed before preflight passes")

        with self.assertRaisesRegex(RuntimeError, "sandbox unavailable"):
            run_local_task(
                Path("C:/project"),
                "Repair it",
                runtime_factory=forbidden_runtime,
                preflight_runner=lambda unused_workspace, unused_task: (_ for _ in ()).throw(
                    RuntimeError("sandbox unavailable")
                ),
            )


if __name__ == "__main__":
    unittest.main()

class AssistantFirstPlannerWiringTest(unittest.TestCase):
    def test_shared_planner_uses_existing_reasoning_manager_and_bounded_context(self) -> None:
        from chatmpd.app import build_shared_intent_planner
        from chatmpd.model_registry import ModelRole

        class Manager:
            endpoint = "http://127.0.0.1:9090"
            def __init__(self): self.calls = []
            def activate(self, role):
                self.calls.append(role)
                return SimpleNamespace(endpoint=self.endpoint)
        class Provider:
            def __init__(self): self.messages = []
            def chat(self, messages):
                self.messages = messages
                return SimpleNamespace(text='{"capability":"chat","requires_workspace":false,"confidence":0.9,"reason":"General answer","missing_context":null,"suggested_action":null}')

        manager = Manager()
        provider = Provider()
        planner = build_shared_intent_planner(
            manager,
            provider_factory=lambda endpoint: provider,
            capability_context="Ready extension: Local helper",
        )
        plan = planner.plan("Explain this simply")
        self.assertEqual(plan.capability, "chat")
        self.assertEqual(manager.calls, [ModelRole.REASONING])
        self.assertIn("Ready extension: Local helper", provider.messages[0]["content"])
        self.assertLessEqual(len(provider.messages[0]["content"]), 12000)

    def test_default_builder_attaches_shared_intent_planner(self) -> None:
        import inspect
        from chatmpd.defaults import build_default_orchestrator
        source = inspect.getsource(build_default_orchestrator)
        self.assertIn("build_shared_intent_planner", source)
        self.assertIn("intent_planner=intent_planner", source)

class PlannerCapabilityContextTest(unittest.TestCase):
    def test_context_exposes_routes_and_ready_extensions_without_metadata(self) -> None:
        from chatmpd.capabilities import CapabilityDescriptor, CapabilityRegistry
        from chatmpd.platform_services import PlatformServices
        registry = CapabilityRegistry()
        for capability_id in ("chat", "coding", "system", "performance", "eso", "vortex", "media"):
            registry.register(CapabilityDescriptor(capability_id, capability_id.title(), f"{capability_id} route"))
        registry.register(CapabilityDescriptor("helper_ext", "Friendly helper", "Useful extension", kind="extension", metadata={"token":"DO_NOT_LEAK"}))
        registry.register(CapabilityDescriptor("broken_ext", "Broken helper", "Unavailable", kind="extension", health="unavailable"))
        services = PlatformServices.__new__(PlatformServices)
        services.capabilities = registry
        context = services.planner_capability_context()
        for capability_id in ("chat", "coding", "system", "performance", "eso", "vortex", "media"):
            self.assertIn(capability_id, context)
        self.assertIn("Friendly helper", context)
        self.assertNotIn("Broken helper", context)
        self.assertNotIn("DO_NOT_LEAK", context)
