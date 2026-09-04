# ChatMPD Prompt Guide

ChatMPD is designed for normal language. You do not need special syntax, long role prompts, or token budgeting for routine work. State the result you want and let the router choose the local model, skill, specialist, or tool.

For complex work, use this structure:

**Goal → Context → Constraints → Desired result → Verification**

Example:

> Goal: diagnose my ESO addon crashes. Context: controller on PC; minimap, HarvestMap, crafting automation, Personal Assistant, treasure/survey/lead locations are required. Constraints: preserve required addons and do not change anything while ESO or Minion is running. Desired result: identify incompatible or redundant addons and a safe repair order. Verification: rescan manifests/dependencies and report remaining critical issues.

The Control Center → Prompt Guide can build this structure for you and copy it to the composer.
## Useful prompt patterns

### Build or change code

`Fix <behavior>. Preserve <interfaces/data>. Work only inside this project. Finish only when the relevant verification passes.`

### Diagnose before changing anything

`Inspect <system/problem> first. Explain the evidence and likely root cause. Make only reversible changes that are justified by the evidence; ask before critical-impact changes.`

### Research or compare

`Answer <question>. Prioritize reliable evidence, separate confirmed facts from uncertainty, and give me the decision-relevant differences rather than a generic summary.`

### Work with local files or knowledge

`Use the attached/indexed files as the source of truth for <question>. Cite filenames/sections in the answer and tell me when the files do not contain enough evidence.`

### Create media

`Create <image/video/audio> of <subject>. Style: <style>. Format/resolution/duration: <requirements>. Save the local artifact and verify the resulting file metadata.`

### Create an automation

`Repeat <task> every <interval> / check for <condition>. Keep it local. Show the next run and only surface a notification/result when <condition or useful change>.`
## When to be specific

Be specific about things that are truly requirements: files that must not change, addons that must remain, APIs/interfaces that must stay compatible, output format, time or hardware constraints, and what evidence should count as success.

Do not over-specify implementation details unless you care about them. `Make it reliable and verify it` is often better than telling the model exactly which function or library to use.

If a task is large, describe the final objective and important constraints. ChatMPD may decompose it internally into workers/workflows; you do not need to write one prompt per internal step.

## Memory

Use ordinary conversation for temporary context. Use `Remember that ...` when you want a durable fact or preference available across chats. You can inspect and delete durable memories in Control Center → Memory. Conversation transcripts themselves persist until you explicitly delete them.

## Privacy and external tools

ChatMPD defaults to local models and local tools. If you intentionally connect an external API, specify whether network use is allowed and what data may leave the machine. Credentials belong in the encrypted Secrets area, never in ordinary prompts or reusable skills.
