from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from chatmpd.activity import ActivityLog
from chatmpd.assistant_tools import AssistantCapabilityBroker
from chatmpd.extensions import ExtensionManager
from chatmpd.permissions import PermissionProfileStore
from chatmpd.platform_db import PlatformDatabase


class AssistantCapabilityBrokerTest(unittest.TestCase):
    def make_broker(self, root: Path):
        database = PlatformDatabase(root / "platform.db")
        return AssistantCapabilityBroker(
            extensions=ExtensionManager(root / "extensions"),
            permissions=PermissionProfileStore(database),
            activity=ActivityLog(database),
        )

    @staticmethod
    def write_skill(root: Path, folder: str, manifest: str, body: str = "") -> Path:
        target = root / "extensions" / folder
        target.mkdir(parents=True, exist_ok=True)
        (target / "skill.toml").write_text(manifest, encoding="utf-8")
        if body:
            (target / "SKILL.md").write_text(body, encoding="utf-8")
        return target

    def test_relevant_skill_text_is_injected_without_unrelated_skills(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.write_skill(
                root, "eso", '[extension]\nid="skill.eso"\nname="ESO diagnosis"\n'
                'kind="skill"\ndescription="Diagnose ESO Minion addons"\ntags=["eso","minion"]\n',
                "# ESO diagnosis\nInspect manifests and dependencies before changing addons.\n",
            )
            broker = self.make_broker(root)
            self.assertIn("Inspect manifests", broker.skill_context("Diagnose my ESO Minion addons"))
            self.assertEqual(broker.skill_context("Explain photosynthesis"), "")

    def test_safe_plugin_becomes_a_native_tool_and_executes_out_of_process(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = self.write_skill(
                root, "echo", '[extension]\nid="plugin.echo"\nname="Echo helper"\n'
                'kind="plugin"\ndescription="Echo a short input"\nentrypoint="echo.py"\n'
                'tags=["echo"]\nrisk="safe"\n',
            )
            (target / "echo.py").write_text(
                "import json,sys\np=json.load(sys.stdin)\njson.dump({'echo':p.get('input','')},sys.stdout)\n",
                encoding="utf-8",
            )
            broker = self.make_broker(root)
            tools = broker.tools_for_prompt("Please echo hello")
            self.assertEqual(len(tools), 1)
            name = tools[0]["function"]["name"]
            self.assertEqual(name, "ext_plugin_echo")
            self.assertEqual(broker.invoke(name, {"input": "hello"}), {"echo": "hello"})

    def test_critical_or_profile_gated_extensions_are_not_offered_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.write_skill(
                root, "danger", '[extension]\nid="plugin.danger"\nname="Danger"\nkind="plugin"\n'
                'description="Danger action"\nentrypoint="x.py"\ntags=["danger"]\nrisk="critical"\n',
            )
            self.write_skill(
                root, "network", '[extension]\nid="http.lookup"\nname="Lookup"\nkind="http"\n'
                'description="Network lookup"\nendpoint="https://example.com/tool"\n'
                'tags=["lookup"]\npermissions=["network"]\n',
            )
            (root / "extensions" / "danger" / "x.py").write_text("print('{}')\n", encoding="utf-8")
            broker = self.make_broker(root)
            broker.permissions.set_active("safe")
            self.assertEqual(broker.tools_for_prompt("danger lookup"), [])

    def test_tool_schema_can_come_from_manifest_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.write_skill(
                root, "weather", '[extension]\nid="plugin.weather"\nname="Weather helper"\nkind="plugin"\n'
                'description="Weather helper"\nentrypoint="weather.py"\ntags=["weather"]\n'
                '[extension.parameters]\ntype="object"\nrequired=["city"]\n'
                '[extension.parameters.properties.city]\ntype="string"\n',
            )
            (root / "extensions" / "weather" / "weather.py").write_text("print('{}')\n", encoding="utf-8")
            broker = self.make_broker(root)
            tool = broker.tools_for_prompt("weather in Fargo")[0]
            self.assertEqual(tool["function"]["parameters"]["required"], ["city"])
            self.assertEqual(tool["function"]["parameters"]["properties"]["city"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
