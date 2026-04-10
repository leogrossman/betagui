# GitLab Documentation Plan

This repo already has enough structured Markdown to serve as a lightweight
project handbook.

## Simple Option

Do nothing special and use the repository browser:

- keep [overview.md](overview.md) as the main landing page
- use [index.md](index.md) as the table of contents
- link testers first to the control-room entrypoint and runtime checklist

## GitLab Wiki Option

If you want a separate GitLab Wiki, the easiest structure is:

1. Home
2. Runtime Checklist
3. Feature Parity
4. Theory And Operation
5. Testing Workflow
6. Development Workflow
7. PV Inventory
8. Write Paths

The existing files in `docs/` can mostly be copied as-is.

## GitLab Pages Option

If you later want a static documentation site, the current `docs/` structure is
already close to what a small MkDocs or Pages setup would need:

- `docs/index.md` as landing page
- topic pages grouped by user audience
- short, linkable Markdown documents

## Suggested Audience Split

- operators and testers:
  `overview.md`, `runtime_checklist.md`, `feature_parity.md`
- developers:
  `development_workflow.md`, `testing_workflow.md`, `open_features.md`
- maintainers and reviewers:
  `theory_and_operation.md`, `code_walkthrough.md`, `porting_notes.md`

## Optional Static Docs Tooling

An optional MkDocs configuration already exists in the repository root:

- <https://github.com/leogrossman/betagui/blob/main/mkdocs.yml>

If you later install MkDocs, you can use it as a starting navigation structure
instead of reorganizing the Markdown from scratch.
