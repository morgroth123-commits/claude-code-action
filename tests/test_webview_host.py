from __future__ import annotations

import unittest

from chatmpd.webview_host import launch_webview


class _Service:
    url = "http://127.0.0.1:43210/"

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _Orchestrator:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class _Webview:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.windows = []
        self.starts = []

    def create_window(self, title: str, url: str, **options):
        self.windows.append((title, url, options))
        return object()

    def start(self, **options) -> None:
        self.starts.append(options)
        if self.fail:
            raise RuntimeError("webview failed")


class WebviewHostTest(unittest.TestCase):
    def test_launches_one_webview2_window_and_cleans_up(self) -> None:
        service = _Service()
        orchestrator = _Orchestrator()
        webview = _Webview()

        launch_webview(
            orchestrator,
            webview_module=webview,
            service_factory=lambda unused_orchestrator: service,
        )

        self.assertEqual(service.started, 1)
        self.assertEqual(service.stopped, 1)
        self.assertEqual(orchestrator.closed, 1)
        self.assertEqual(len(webview.windows), 1)
        title, url, options = webview.windows[0]
        self.assertEqual(title, "ChatMPD")
        self.assertEqual(url, service.url)
        self.assertGreaterEqual(options["width"], 1100)
        self.assertLessEqual(options["height"], 760)
        self.assertTrue(options["maximized"])
        self.assertLessEqual(options["min_size"][1], 560)
        self.assertEqual(webview.starts[0]["gui"], "edgechromium")

    def test_cleanup_still_runs_when_webview_fails(self) -> None:
        service = _Service()
        orchestrator = _Orchestrator()
        webview = _Webview(fail=True)

        with self.assertRaisesRegex(RuntimeError, "webview failed"):
            launch_webview(
                orchestrator,
                webview_module=webview,
                service_factory=lambda unused_orchestrator: service,
            )

        self.assertEqual(service.stopped, 1)
        self.assertEqual(orchestrator.closed, 1)


if __name__ == "__main__":
    unittest.main()
