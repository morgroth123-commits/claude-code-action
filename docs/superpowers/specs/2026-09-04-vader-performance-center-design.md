# Vader Performance Center Design

## Goal

Add a first-class Performance Center to ChatMPD that measures Vader, identifies real bottlenecks, applies only bounded/reversible optimizations automatically, and proves whether changes improved the machine.

## Product behavior

The Performance Center supports four modes: Analyze only, Balanced, Gaming, and AI / ChatMPD. Analyze only never mutates the host. Balanced, Gaming, and AI apply only ordinary reversible changes that pass ChatMPD's permission policy. Critical-impact changes remain confirmation-gated.

The dashboard reports an overall score plus Gaming, AI, and Balanced scores; CPU, RAM, GPU/VRAM, storage, power-plan, process-contention, and workload-state evidence; the current bottleneck; top competing processes; recommended actions; before/after results; restore controls; and history.
## Analyzer

Sampling is bounded and read-only. It uses Windows/system APIs plus optional `nvidia-smi` telemetry to collect CPU load, memory/commit pressure, storage utilization/free space, GPU load/VRAM/temperature/power/clocks when available, active power plan, top CPU/RAM processes, and whether ESO/ChatMPD/llama.cpp/ComfyUI/LM Studio/Bionic are active.

The analyzer converts evidence to normalized 0-100 scores and a small set of bottleneck findings. Missing telemetry lowers confidence rather than inventing values. Reports are persisted locally for before/after comparison.

## Optimizer

Safe automatic actions are limited to ChatMPD-owned runtime coordination and reversible Windows power-plan selection. Gaming mode protects the game by releasing/suppressing ChatMPD GPU work and using the existing ESO-safe model behavior. AI mode favors local inference/media when no game is active. Balanced restores the captured baseline power plan and normal ChatMPD behavior.

The optimizer never disables Defender/firewall/VBS, never edits boot/firmware/disk/security/account settings, never uses realtime priority, never kills unrelated user programs, and never changes BIOS/overclock/undervolt settings automatically.
## Adaptive mode and recovery

Adaptive mode polls at low frequency. When `eso64.exe` appears it shifts ChatMPD-owned resources to Gaming behavior; when the game exits it restores the user's selected baseline mode. Adaptive mode does not terminate unrelated processes.

Before a profile change, ChatMPD records the active Windows power plan and optimizer state in its platform database. Restore re-applies that captured state. Every optimization and restore is written to the activity log with bounded evidence.

## Integration

Create `chatmpd/performance.py` for measurement, scoring, persistence, and optimization. Register it in `PlatformServices`, expose `/api/platform/performance` endpoints, and add a Performance section to the existing Control Center. No new mandatory third-party runtime dependency is required.

## Verification

Unit tests cover scoring, missing telemetry, optimizer policy, restore, history, and adaptive transitions. API/UI tests cover the Control Center surface. A live Vader smoke must collect a report and run Analyze-only without mutation; a reversible profile smoke may change only the power plan/ChatMPD-owned state and must restore the original plan before release.