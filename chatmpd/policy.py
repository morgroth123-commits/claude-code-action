from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionPolicy:
    writable_paths: list[str]
    allowed_commands: list[list[str]]
    required_checks: list[list[str]]

    def permits_write(self, relative_path: str) -> bool:
        candidate = relative_path.replace("\\", "/").strip("/").casefold()
        for configured_path in self.writable_paths:
            rule = configured_path.replace("\\", "/").strip("/").casefold()
            if rule == "**" or candidate == rule:
                return True
            if rule.endswith("/**"):
                root = rule[:-3].rstrip("/")
                if candidate == root or candidate.startswith(f"{root}/"):
                    return True
        return False

    def permits_command(self, argv: list[str]) -> bool:
        return tuple(argv) in {tuple(command) for command in self.allowed_commands}

    def is_required_check(self, argv: list[str]) -> bool:
        return tuple(argv) in {tuple(command) for command in self.required_checks}
