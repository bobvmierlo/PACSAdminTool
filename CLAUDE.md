# PACSAdminTool — Claude Instructions

## Changelog format

When writing a release-notes entry to `CHANGELOG.md`, always follow this structure:

```markdown
## vX.Y.Z — YYYY-MM-DD

### Fixed — [#<PR>](https://github.com/bobvmierlo/PACSAdminTool/pull/<PR>)

- One bullet per fix, plain language, no file paths or function names.

### New — [#<PR>](https://github.com/bobvmierlo/PACSAdminTool/pull/<PR>)

- **Feature name** — one-line description of what it does for the user.

### Improved — [#<PR>](https://github.com/bobvmierlo/PACSAdminTool/pull/<PR>)

- One bullet per improvement.

### Breaking — [#<PR>](https://github.com/bobvmierlo/PACSAdminTool/pull/<PR>)

- What changed and what users must do to migrate.
```

Rules:
- Use only the sections that apply — omit empty ones.
- Bundle all PRs belonging to the same release version under one `## vX.Y.Z` heading, each PR in its own `###` section.
- Determine the release version from `__version__.py` and the latest git tag.
- Classify dependency-only or internal PRs as "Internal change — no release note" and skip them.
- Write for end users, not contributors. No jargon, file paths, or commit SHAs.
- Bold labels (`**Feature name**`) on New/Improved items to aid scanning.
- New entries go at the top of the file, above older releases.
