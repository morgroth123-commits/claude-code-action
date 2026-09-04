from __future__ import annotations

import unittest

from chatmpd.capabilities import CapabilityDescriptor, CapabilityRegistry


class CapabilityRegistryTest(unittest.TestCase):
    def test_register_list_search_and_duplicate_rejection(self) -> None:
        registry = CapabilityRegistry()
        item = CapabilityDescriptor(
            capability_id="builtin.system",
            title="Windows diagnostics",
            description="Inspect local Windows state",
            kind="builtin",
            version="1",
            risk="safe",
            permissions=("system.read",),
        )
        registry.register(item)

        self.assertEqual(registry.get("builtin.system"), item)
        self.assertEqual(registry.list()[0].title, "Windows diagnostics")
        self.assertEqual(registry.search("windows")[0].capability_id, "builtin.system")
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(item)
