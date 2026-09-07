"""Assembly and high-level operations for ChatMPD platform services."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .activity import ActivityLog
from .attachments import AttachmentStore
from .assistant_tools import AssistantCapabilityBroker
from .automation_engine import AutomationScheduler, AutomationStore
from .capabilities import CapabilityDescriptor, CapabilityRegistry
from .civitai import CivitaiMCP
from .desktop_control import DesktopController
from .exporter import PackExporter
from .extension_wizard import ExtensionWizard
from .extensions import ExtensionManager
from .hardware import HardwareProfile, detect_hardware, recommend_model_tier
from .knowledge import KnowledgeLibrary
from .lmstudio import BionicCompanion, LMStudioDiscovery, LMStudioProvider
from .memory import MemoryRecord, MemoryStore
from .model_lab import ModelBenchmarkStore, ModelInventory
from .model_registry import ModelRegistry
from .mod_sources import EsoUiCatalog, NexusModsCatalog
from .packs import CapabilityPackManager
from .performance import PerformanceAnalyzer, PerformanceCenter, PerformanceEvidence, PerformanceStore, VaderOptimizer
from .permissions import PermissionProfileStore
from .platform_db import PlatformDatabase
from .platform_doctor import PlatformDoctor
from .platform_paths import PlatformPaths
from .prompts import PromptGuide
from .recovery import RecoveryCenter
from .secrets_vault import SecretsVault
from .vision import LocalVision
from .voice import LocalVoice
from .workflows import WorkflowStore


_BUILTINS = (
    ("chat", "Local chat", "General local reasoning and conversation."),
    ("coding", "Verified coding", "Workspace-bounded autonomous coding with verification."),
    ("system", "Windows diagnostics", "Read-only inspection and permission-gated host work."),
    ("media", "Local media", "Local image/video generation through managed ComfyUI."),
    ("eso", "ESO specialist", "ESO addon diagnosis with ESOUI/Minion ecosystem awareness."),
    ("vortex", "Vortex specialist", "Vortex/mod state inspection with Nexus Mods integration."),
    ("memory", "Long-term memory", "Persistent user-controlled memory and retrieval."),
    ("knowledge", "Knowledge library", "Local document extraction and retrieval."),
    ("workflows", "Reusable workflows", "Persistent replayable ChatMPD workflows."),
    ("automation", "Local automation", "Persistent recurring and conditional local tasks."),
    ("voice", "Local voice", "Windows TTS and optional local Whisper transcription."),
    ("vision", "Local vision", "Managed screenshots and local-only vision routing."),
    ("performance", "Performance Center", "Evidence-based Vader analysis and reversible optimization."),
)

@dataclass
class PlatformServices:
    paths: PlatformPaths
    database: PlatformDatabase
    memory: MemoryStore
    knowledge: KnowledgeLibrary
    attachments: AttachmentStore
    capabilities: CapabilityRegistry
    extensions: ExtensionManager
    hardware: HardwareProfile
    models: ModelInventory
    workflows: WorkflowStore
    automations: AutomationStore
    activity: ActivityLog
    assistant_tools: AssistantCapabilityBroker
    permissions: PermissionProfileStore
    secrets: SecretsVault
    recovery: RecoveryCenter
    exporter: PackExporter
    prompts: PromptGuide
    packs: CapabilityPackManager
    wizard: ExtensionWizard
    doctor: PlatformDoctor
    voice: LocalVoice
    vision: LocalVision
    desktop: DesktopController
    bionic: BionicCompanion
    lmstudio_installation: Any | None
    esoui: EsoUiCatalog
    nexus: NexusModsCatalog
    civitai: CivitaiMCP
    performance: PerformanceCenter
    automation_scheduler: AutomationScheduler | None = None

    def bind_automation_runner(self, runner: Callable[[str], Any]) -> None:
        if self.automation_scheduler is not None:
            self.automation_scheduler.stop()
        self.automation_scheduler = AutomationScheduler(self.automations, runner)
        self.automation_scheduler.start()

    def close(self) -> None:
        self.performance.close()
        if self.automation_scheduler is not None:
            self.automation_scheduler.stop()
            self.automation_scheduler = None

    def planner_capability_context(self, *, max_extensions: int = 24) -> str:
        """Return a bounded, secret-free catalog for assistant-first intent planning."""

        route_ids = ("chat", "coding", "system", "performance", "eso", "vortex", "media")
        lines = ["Top-level routes:"]
        for capability_id in route_ids:
            try:
                item = self.capabilities.get(capability_id)
            except KeyError:
                continue
            if not item.enabled or item.health != "ready":
                continue
            lines.append(f"- {capability_id}: {item.title} ? {item.description}"[:600])
        extensions = [
            item for item in self.capabilities.list(enabled_only=True)
            if item.kind != "builtin" and item.health == "ready"
        ][: max(0, min(int(max_extensions), 64))]
        if extensions:
            lines.append("Ready extensions available through normal chat/tool use:")
            for item in extensions:
                lines.append(f"- {item.title}: {item.description}"[:600])
        return "\n".join(lines)[:6_000]

    def retrieval_context(self, prompt: str, *, max_items: int = 8) -> str:
        terms = []
        for term in re.findall(r"[\w-]{4,}", str(prompt), flags=re.UNICODE):
            folded = term.casefold()
            if folded not in terms:
                terms.append(folded)
        memories: dict[str, MemoryRecord] = {}
        knowledge: dict[str, Any] = {}
        for term in terms[:12]:
            for item in self.memory.search(term, limit=3):
                memories.setdefault(item.memory_id, item)
            for hit in self.knowledge.search(term, limit=3):
                knowledge.setdefault(hit.chunk_id, hit)
        lines: list[str] = []
        if memories:
            lines.append("Relevant durable memories:")
            for item in list(memories.values())[:max_items]:
                lines.append(f"- {item.content} [source: {item.source}]")
        if knowledge:
            lines.append("Relevant local knowledge:")
            for hit in list(knowledge.values())[:max_items]:
                excerpt = " ".join(hit.text.split())[:700]
                lines.append(f"- {excerpt} [source: {hit.title} | {hit.path}]")
        skill_context = self.assistant_tools.skill_context(prompt)
        if skill_context:
            lines.append("Relevant installed skill guidance:")
            lines.append(skill_context)
        return "\n".join(lines)

    def capture_explicit_memory(self, text: str) -> MemoryRecord | None:
        value = " ".join(str(text).split()).strip()
        match = re.match(r"^(?:please\s+)?remember(?:\s+that)?\s+(.+)$", value, flags=re.I)
        if not match:
            return None
        content = match.group(1).strip().rstrip(".")
        if len(content) < 3:
            return None
        if any(item.content.casefold() == content.casefold() for item in self.memory.list(limit=1000)):
            return None
        record = self.memory.add(content, kind="explicit", source="explicit-user-instruction", pinned=True)
        self.activity.record("memory", "Saved an explicit user memory.", details={"memory_id": record.memory_id})
        return record

    def summary(self) -> dict[str, Any]:
        lm_ready = False
        lm_models: tuple[str, ...] = ()
        if self.lmstudio_installation is not None:
            provider = LMStudioProvider("http://127.0.0.1:1234", timeout=0.35)
            try:
                lm_models = provider.models()
                lm_ready = bool(lm_models)
            except Exception:
                pass
        return {
            "memory_count": len(self.memory.list(limit=1000)),
            "knowledge_count": len(self.knowledge.list()),
            "capabilities": len(self.capabilities.list()),
            "capability_count": len(self.capabilities.list()),
            "extensions": len(self.extensions.discover()),
            "extension_count": len(self.extensions.discover()),
            "workflows": len(self.workflows.list()),
            "automations": len(self.automations.list()),
            "permission_profile": self.permissions.active_name(),
            "performance": self.performance.status(),
            "hardware": self.hardware.as_dict(),
            "recommended_model_tier": recommend_model_tier(self.hardware),
            "local_models": len(self.models.registry.models),
            "lm_studio": {
                "available": self.lmstudio_installation is not None,
                "source": None if self.lmstudio_installation is None else self.lmstudio_installation.source,
                "executable": None if self.lmstudio_installation is None else str(self.lmstudio_installation.lms_path),
                "server_ready": lm_ready,
                "models": list(lm_models),
            },
            "bionic": self.bionic.status(),
            "voice": self.voice.transcription_health(),
            "vision": self.vision.health(),
            "esoui": self.esoui.policy(),
            "nexus": {"api": self.nexus.api_root, "site": self.nexus.site_root, "api_key_configured": "nexus-api-key" in self.secrets.names()},
            "civitai": self.civitai.status(),
        }

def build_platform_services(
    *,
    paths: PlatformPaths | None = None,
    model_registry: ModelRegistry | None = None,
    hardware_probe: Callable[[], HardwareProfile | None] | None = None,
    performance_probe: Callable[[], PerformanceEvidence] | None = None,
    power_getter: Callable[[], tuple[str, str]] | None = None,
    power_setter: Callable[[str], None] | None = None,
) -> PlatformServices:
    paths = paths or PlatformPaths.default()
    for folder in (paths.root, paths.extensions, paths.data, paths.attachments, paths.artifacts, paths.exports, paths.recovery):
        folder.mkdir(parents=True, exist_ok=True)
    database = PlatformDatabase(paths.data / "chatmpd.db")
    registry = CapabilityRegistry()
    for capability_id, title, description in _BUILTINS:
        registry.register(CapabilityDescriptor(capability_id, title, description))
    extension_manager = ExtensionManager(paths.extensions)
    for descriptor in extension_manager.discover():
        if descriptor.capability_id in {item.capability_id for item in registry.list()}:
            continue
        registry.register(descriptor)

    installation = LMStudioDiscovery().discover()
    bionic = BionicCompanion()
    registry.register(CapabilityDescriptor(
        "lmstudio", "LM Studio local backend",
        "OpenAI-compatible local inference and model management.",
        health="ready" if installation is not None else "unavailable",
        metadata={"source": None if installation is None else installation.source},
    ))
    registry.register(CapabilityDescriptor(
        "bionic", "LM Studio Bionic companion",
        "Optional local agent workspace powered by the LM Studio runtime.",
        health="ready" if bionic.status()["installed"] else "unavailable",
    ))
    registry.register(CapabilityDescriptor("desktop", "Desktop control", "Permission-gated local computer input.", enabled=False, risk="critical"))
    registry.register(CapabilityDescriptor("esoui", "ESOUI catalog", "Canonical public ESO addon repository used with Minion local state."))
    registry.register(CapabilityDescriptor("nexus", "Nexus Mods", "Canonical Nexus/Vortex repository integration with optional API key.", permissions=("network",)))
    registry.register(CapabilityDescriptor("civitai", "Civitai MCP", "Remote Streamable HTTP MCP for Civitai browse and permission-gated account actions.", permissions=("network",)))

    detected = hardware_probe() if hardware_probe is not None else detect_hardware()
    if detected is None:
        detected = HardwareProfile("unknown", 1, 0.0, "unknown", 0.0)
    models = ModelInventory(model_registry or ModelRegistry(()), ModelBenchmarkStore(database))
    memory = MemoryStore(database)
    knowledge = KnowledgeLibrary(database)
    attachments = AttachmentStore(database, paths.attachments)
    permissions = PermissionProfileStore(database)
    secrets = SecretsVault(database)
    civitai = CivitaiMCP(secrets=secrets)
    registry.replace(
        registry.get("civitai"),
        lambda tool_name, arguments, confirmed=False: civitai.call(
            str(tool_name), dict(arguments), confirmed=bool(confirmed)
        ),
    )
    activity = ActivityLog(database)
    assistant_tools = AssistantCapabilityBroker(
        extensions=extension_manager, permissions=permissions, activity=activity
    )
    performance_store = PerformanceStore(database)
    performance_analyzer = PerformanceAnalyzer(performance_store, evidence_probe=performance_probe)
    optimizer_kwargs = {"database": database, "permissions": permissions, "activity": activity}
    if power_getter is not None:
        optimizer_kwargs["power_getter"] = power_getter
    if power_setter is not None:
        optimizer_kwargs["power_setter"] = power_setter
    performance = PerformanceCenter(performance_analyzer, VaderOptimizer(**optimizer_kwargs))
    voice = LocalVoice()
    vision = LocalVision(paths.artifacts / "screenshots")
    desktop = DesktopController(policy=permissions, enabled=False)
    esoui = EsoUiCatalog()
    nexus = NexusModsCatalog(
        api_key_provider=lambda: secrets.get("nexus-api-key") if "nexus-api-key" in secrets.names() else ""
    )
    return PlatformServices(
        paths=paths,
        database=database,
        memory=memory,
        knowledge=knowledge,
        attachments=attachments,
        capabilities=registry,
        extensions=extension_manager,
        hardware=detected,
        models=models,
        workflows=WorkflowStore(database),
        automations=AutomationStore(database),
        activity=activity,
        assistant_tools=assistant_tools,
        permissions=permissions,
        secrets=secrets,
        recovery=RecoveryCenter(database, paths.recovery),
        exporter=PackExporter(),
        prompts=PromptGuide(),
        packs=CapabilityPackManager(database=database),
        wizard=ExtensionWizard(paths.extensions),
        doctor=PlatformDoctor(paths=paths, extensions=extension_manager),
        voice=voice,
        vision=vision,
        desktop=desktop,
        bionic=bionic,
        lmstudio_installation=installation,
        esoui=esoui,
        nexus=nexus,
        civitai=civitai,
        performance=performance,
    )
