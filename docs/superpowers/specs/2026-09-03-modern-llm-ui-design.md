# ChatMPD Modern LLM UI Design

**Date:** 2026-09-03
**Status:** Approved for implementation

## Objective

Replace the current Tkinter command console with a modern conversational desktop shell that feels immediately familiar to users of current ChatGPT, Claude, and Gemini interfaces while remaining visually and functionally ChatMPD.

The redesign must preserve the verified ChatMPD 0.2 backend: model routing, autonomous coding sandbox, ESO/Vortex specialists, media generation, mobile pairing, local conversations, and critical-action policy.

The UI must hide implementation complexity. Users should not need to know model filenames, llama.cpp flags, ComfyUI nodes, Minion metadata, or specialist routing rules.

## Visual direction

Use a restrained, contemporary LLM application language rather than a branded clone:

- dark and light themes with system-following default
- neutral surfaces, subtle borders, generous spacing, rounded controls
- ChatMPD retinal icon as the only strong brand mark
- one accent color derived from the existing warm/orange ChatMPD identity
- readable system font stack with code-specific monospace styling
- no ornamental gradients, giant branding blocks, or dashboard-like cards in the primary chat flow
- responsive density suitable for desktop, tablet, and phone

The experience should feel closer to a current LLM client than to a traditional desktop utility.
## Primary desktop layout

### Left sidebar

A collapsible sidebar provides navigation rather than task controls.

Top section:
- New chat button
- Search conversations
- optional project/workspace shortcut

Conversation section:
- pinned conversations first
- recent conversations grouped chronologically
- title generated from the first useful user request
- context menu for rename, pin/unpin, branch, and delete
- active conversation clearly indicated without heavy borders

Bottom section:
- Mobile access
- Settings
- local runtime/status indicator

When collapsed, only compact icon actions remain. On narrow windows and mobile, the sidebar becomes a temporary overlay and closes after a conversation is selected.

### Main conversation pane

The transcript is the visual center of the product. It uses a comfortable maximum reading width while allowing wide code, tables, media, or artifacts to expand when necessary.

Messages render as semantic conversation blocks rather than raw JSON or a terminal log. User messages are visually distinct but compact. Assistant responses use rich markdown with headings, lists, tables, inline code, fenced code, links, and copy controls.
Operational activity appears inline only while relevant:
- concise working state near the current assistant turn
- expandable activity/details section for routing, model role, coding checks, ESO findings, media job state, and system actions
- completed activity collapses by default so the conversation remains readable
- errors appear as understandable recovery messages, not stack traces

Generated files appear as result cards with filename, type, path, open/copy actions, and a preview when practical. Images and video use inline previews. Coding results show changed files and verification state without dumping the entire run record.

### Top bar

Keep the top bar visually quiet. It contains:
- sidebar toggle
- current conversation title
- current model/capability indicator when useful
- optional project/workspace chip
- overflow menu for conversation actions

No permanent status dashboard occupies primary space.

### Composer

A floating composer is anchored at the bottom of the conversation and remains visible while scrolling.

It includes:
- auto-growing multiline text area
- attachment/project button
- current project chip when a workspace is selected
- send button that becomes a stop/cancel control during supported operations
- keyboard behavior: Enter sends, Shift+Enter inserts newline; configurable if needed
- drag-and-drop support for files and folders where the backend can safely accept them
- compact capability/model affordance only when manual override is genuinely useful

The composer fades the transcript underneath it rather than placing the conversation inside a separate framed panel.
## Conversation and artifact behavior

ChatMPD conversations become first-class local objects rather than only the currently open message list.

Required behavior:
- list, open, create, rename, pin, branch, search, and delete local conversations
- preserve messages across application restarts
- keep conversation data local by default
- allow one active conversation per desktop window
- keep mobile and desktop views pointed at the same persisted conversation state

For large outputs, use an optional right-side artifact/result pane inspired by modern assistant workspaces. It opens only when useful for code, long documents, images, video, structured reports, or generated files. Closing the pane never deletes the artifact.

## Desktop technology

Replace Tkinter as the primary product shell with an HTML/CSS/JavaScript frontend hosted in a native Windows WebView2 window.

Recommended implementation:
- `pywebview` as the thin native host using Microsoft Edge WebView2 on Windows
- a small loopback-only ChatMPD HTTP application for frontend assets and API calls
- existing Python orchestrator remains authoritative for all model/tool execution
- desktop API binds only to `127.0.0.1` on a dynamically selected port
- current LAN/mobile gateway continues to require device pairing and bearer credentials
- llama.cpp and ComfyUI remain loopback-only and are never exposed directly to WebView/mobile clients

The same frontend asset bundle should serve both desktop and mobile so behavior and visual design do not diverge.

If WebView2 is unavailable, ChatMPD should show a bounded recovery message and offer the local browser UI rather than silently falling back to the old Tk interface.
## Execution and progress model

The browser shell must not block while a command executes. Replace the current synchronous request/response UI contract with a local job model:

- submitting a message creates a job id immediately
- the frontend receives structured progress events through server-sent events or an equivalent loopback stream
- events identify routing, model activation, tool activity, verification, media generation, completion, and bounded errors
- final results are persisted into the active conversation before the job reports complete
- duplicate concurrent commands are rejected or queued explicitly rather than racing shared model state

Stop/cancel is cooperative and safety-aware:
- chat inference may stop immediately by cancelling the owned request/runtime
- coding stops between atomic tool operations and never during an atomic file replacement
- media uses the backend interrupt mechanism where supported
- cancellation never reports success and preserves any already-created recovery metadata

## Mobile connection flow

Mobile setup must be simple enough to complete without manually transcribing connection details.

From the desktop Mobile access panel, starting mobile access displays:
- **Copy setup link**: copies a short-lived, single-use URL containing the LAN address and temporary pairing code
- **Copy address** and **Copy code** as explicit fallbacks
- a QR code representing the same setup URL

Opening the setup link on the phone pre-fills the pairing code and a reasonable device name; the user confirms with one **Pair this device** action. The temporary code is invalidated after successful exchange. The long-lived bearer credential is created only after pairing and is never embedded in the URL. Manual pairing remains available, and this flow must not change Windows Firewall or other Windows security settings.

## Security and privacy

- desktop server accepts loopback clients only
- LAN/mobile access remains off until explicitly started
- mobile clients retain the existing pairing/token model
- no model backend is exposed directly to the LAN
- no credentials, environment secrets, or raw protected state are sent to the frontend
- rich output is escaped/sanitized before rendering to prevent generated HTML/script execution
- file-opening actions are limited to known result paths or explicit user-selected paths
- critical host actions continue through the existing confirmation gate

## Accessibility and interaction quality

- complete keyboard navigation and visible focus states
- minimum WCAG AA contrast for text and controls
- system/light/dark theme support
- browser zoom and text scaling remain functional
- reduced-motion preference disables nonessential animation
- semantic landmarks and ARIA labels for sidebar, transcript, composer, dialogs, and artifact pane
- screen-reader announcements for working, completion, cancellation, and errors
## Migration and compatibility

The current Tk window is retained only as a temporary fallback/test fixture during development, then removed from the default launch path once the WebView2 shell passes release verification.

Existing conversation JSON should be migrated in place or read compatibly; no existing local conversations are intentionally discarded. Existing desktop shortcut and `ChatMPD.exe` identity remain unchanged after rebuilding.

The orchestrator, model registry/runtime, coding engine, host policy, ESO/Vortex specialists, ComfyUI adapters, media models, mobile credentials, and output directories are not redesigned by this UI project.

## Release acceptance criteria

A replacement build is acceptable only when all of the following are demonstrated:

1. Desktop launches into the new WebView2 conversation UI with the ChatMPD icon and no console window.
2. New chat, conversation history, search, rename, pin, branch, and delete work after restart.
3. Chat responses render as rich conversation content rather than raw JSON.
4. A real gpt-oss reasoning request succeeds from the new desktop composer.
5. A disposable autonomous coding task edits and verifies successfully from the new UI.
6. ESO, Vortex, and system specialist results render as readable structured responses.
7. Real image and video outputs appear as result cards/previews.
8. Mobile uses the same frontend visual system and still requires pairing.
9. Desktop and mobile cannot race the shared orchestrator.
10. Cancel/stop behaves safely for the supported operation types.
11. Light, dark, keyboard-only, narrow-window, and mobile layouts are usable.
12. Full automated test suite passes after the final UI changes.
13. PyInstaller build succeeds and the packaged executable launch/close smoke leaves no owned llama.cpp, ComfyUI, or ChatMPD process behind.
14. The verified build replaces the installed binary and existing desktop shortcut target without changing Windows security settings.

## Non-goals

This project does not clone another vendor's logos, exact visual trade dress, proprietary source code, account/cloud synchronization, or backend services. It adopts familiar interaction conventions while preserving a distinct ChatMPD identity and local-first architecture.