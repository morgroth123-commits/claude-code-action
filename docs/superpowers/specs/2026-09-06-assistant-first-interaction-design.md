# ChatMPD Assistant-First Interaction Design

**Date:** 2026-09-06
**Status:** Approved for implementation
**Target:** ChatMPD 0.4 interaction layer

## Objective

Make ChatMPD behave like a modern general-purpose assistant from the user's point of view. A user should be able to describe a goal in ordinary language without knowing capability names, coding syntax, model roles, tool names, local paths, routing rules, or backend terminology.

The existing local-first architecture remains authoritative. This project changes how intent is understood, how context is gathered, how actions are exposed, and how the UI guides the user. It does not bypass ChatMPD's permission, recovery, verification, or critical-action boundaries.

## Product contract

Every ordinary request enters one conversational front door. ChatMPD should determine whether the request needs:
- a normal answer,
- project-aware coding,
- local Windows/system work,
- ESO or Vortex expertise,
- local media generation/editing,
- memory or indexed knowledge,
- an installed extension/tool,
- a workflow or automation,
- or a conversational request for one missing piece of context.

Users should not have to select a mode before asking. Advanced controls may override defaults, but normal use should not depend on them.

## Intent and planning

Replace keyword-first routing with a two-stage decision model:

1. `IntentPlanner` creates a bounded structured plan from the request plus relevant context.
2. `RequestRouter` remains as a deterministic fallback and policy guard when planning is unavailable, invalid, or ambiguous.

The planner is not permitted to invent tools or capabilities. It receives an explicit catalog of available routes and produces only a schema-validated `IntentPlan`.

`IntentPlan` includes:
- `capability`: one supported route,
- `requires_workspace`: whether a project folder is required,
- `confidence`: bounded 0..1 value,
- `reason`: short user-safe explanation,
- `missing_context`: optional plain-language context need,
- `suggested_action`: optional UI action identifier.

Low-confidence or missing-context decisions should not silently route destructive work. They should return a conversational recovery/next-step response.

## Context resolution

The orchestrator should consider:
- active conversation,
- selected workspace,
- conversation attachments,
- relevant durable memory/knowledge retrieval already available to the assistant,
- installed and ready capabilities,
- permission profile.

Workspace handling must be conversational. If the user asks to edit/fix/build a project and no project is selected, return a structured `needs_context` result with an action to choose a project rather than raising a raw exception.

Attachments should be first-class conversation context. The web service should expose safe attachment upload/list/delete routes backed by the existing `AttachmentStore`. Attachments remain managed local copies and obey existing size/path rules.

## Action and confirmation model

Safe read-only and already-authorized actions may execute automatically.

When a request crosses an existing confirmation gate, the result should contain a bounded `confirmation` descriptor:
- plain-language title,
- plain-language consequence,
- stable action token,
- confirm/cancel UI labels.

The frontend presents this inline in the conversation. It must not expose raw permission categories or internal policy objects.

Critical host actions remain confirmation-gated even in Autonomous mode. This UI project does not weaken permanent safety rules.

## Conversational UI

The main screen remains conversation-first:
- sidebar: new chat, search, recent/pinned chats;
- main pane: transcript, working state, composer;
- optional artifact pane for substantial outputs;
- advanced platform controls moved behind a quieter Settings/Advanced surface.

The composer should support:
- normal text,
- file attachment button,
- drag/drop file upload,
- attachment chips with remove action,
- project context chip with plain-language label,
- Enter to send and Shift+Enter for newline,
- Stop while a supported job is active.

The welcome state should use simple suggestion buttons instead of backend feature descriptions. Suggestions are examples, not modes.

## Progressive disclosure

Normal users should not need to understand:
- model filenames or quantization,
- llama.cpp/LM Studio backend details,
- capability IDs,
- tool schemas,
- raw automation interval seconds,
- raw workspace/path semantics,
- routing reasons.

Settings keeps technical information available under Advanced. The default surfaces use human labels and strong defaults.

## Status, errors, and recovery

Working states should be meaningful and evidence-based. The backend may expose a short `status_label` such as:
- Understanding request,
- Checking project,
- Working locally,
- Verifying changes,
- Creating media,
- Finishing up.

Do not invent percentages or hidden chain-of-thought.

User-facing errors should include:
- what ChatMPD could not do,
- the smallest next action,
- an optional action button when the UI can resolve it.

Raw exception class names, stack traces, tool payloads, and backend jargon remain hidden by default.

## Results and artifacts

`CommandResult` should support optional structured UI metadata while preserving the existing `capability`, `message`, and `details` contract.

Useful metadata includes:
- `status`,
- `status_label`,
- `needs_context`,
- `confirmation`,
- `artifacts`,
- `suggestions`.

Large files, images, video, structured reports, or generated documents open in the existing artifact pane. Ordinary answers remain inline.

## Accessibility and responsive behavior

Preserve:
- keyboard navigation,
- visible focus,
- system/light/dark themes,
- reduced motion,
- responsive sidebar,
- safe DOM rendering using text nodes rather than model-provided HTML.

Add clear labels/tooltips for icon-only actions and keep primary actions understandable without technical vocabulary.

## Compatibility

Preserve:
- existing persisted conversations and memory,
- existing specialist handlers,
- coding sandbox and verification boundary,
- current model runtime manager,
- permissions/recovery/secrets,
- mobile pairing/auth model,
- extension/tool broker,
- existing deterministic router as fallback.

No cloud service, subscription, account requirement, telemetry dependency, or mandatory API key is added.

## Acceptance criteria

1. A user can ask a normal question and receive a normal answer without selecting a mode.
2. Ambiguous coding requests with no workspace produce a guided project-selection action instead of a raw error.
3. Intent planning can route semantically phrased requests that contain none of the old keyword triggers.
4. Planner output is schema-validated and cannot invent unknown capabilities.
5. Deterministic routing still works when the planner is absent or fails.
6. Files can be attached from the composer, listed as chips, removed before/after use, and remain local managed copies.
7. Installed extension tools remain automatically available when relevant.
8. Confirmation-gated actions surface an inline human-readable confirmation instead of bypassing policy.
9. Control Center technical surfaces are visually de-emphasized; everyday use stays in chat.
10. Errors provide plain-language recovery actions.
11. Desktop and mobile use the same conversational interaction model.
12. Existing focused tests plus the full test suite pass.
13. PyInstaller build succeeds.
14. Packaged `ChatMPD.exe` launches and the primary conversation flow works.
15. CodeRabbit review is run against the final diff and all material issues are resolved or explicitly reported.
