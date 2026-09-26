# Validation Notes

**English** · [简体中文](VALIDATION.zh-CN.md)

Current version: 0.3.0.

## 0.3.0 file editing and search (2026-09-26)

The isolated Windows / Python 3.13.5 portable suite recorded **111 passed, 33 skipped**. Skips cover native macOS commands, desktop probes, ACL/xattr metadata, MCP entry-point execution, and unavailable local symlink privileges. Native macOS results are recorded by this PR’s Actions; portable results do not substitute for them.

New cases cover unique exact matching and overlapping ambiguity, Chinese/emoji, UTF-8 BOM, UTF-16 byte order, GB18030, newlines, version conflicts, backup failure, external mutation, pause, protected paths, search result/byte/entry/time limits, and content-free audit records. A real MCP stdio workflow covers discovery, search, read, edit, backup, stale-version rejection and pause; its macOS entry point runs only on a native runner.

Independent static code review completed. Tests use separate checkouts and synthetic temporary files and do not upgrade a running installation. See [file tool contracts](docs/file-tools.md).

## Executed 0.2.0 results (2026-09-23)

GitHub Actions for commit `2242420` (PR #1, run `35812101522`) completed with **96 passed, 0 skipped** on macOS 15 / Apple Silicon / Python 3.13, and **72 passed, 24 skipped** on Windows portable. The local Windows virtual environment recorded 71 passed, 25 skipped; local symlink privileges account for the additional skip.

The macOS run includes actual subprocess and MCP stdio-session shutdown tests, not just imports. It exposed and verified a fix for cleanup after the group leader exits: cleanup does not depend on querying a dead leader's PGID, and Darwin's all-zombie-group EPERM is ignored only after confirming there are no live group members. Real permission failures remain failures. Both targeted simulated cases and native child-process regressions passed.

These checks do not replace physical desktop authorization, input, multi-display or cross-version/hardware validation below.

## 0.2.0 command regression

New coverage includes disabled-by-default/local approval, private environment filtering, MCP registration, argument limits, Unicode pagination/truncation, and real macOS runner processes for argv/cwd/stdin, dual-pipe draining, nonzero exit, incremental decoding, timeout, cancellation, pause, revocation, SIGTERM-resistant processes, ordinary child cleanup, concurrency/retention limits, executable symlinks and stdio session shutdown. Command tests do not request or grant desktop TCC permissions.

Windows runs portable logic and skips real POSIX/macOS stdio tests; macOS CI executes actual subprocesses. Exact pass counts are recorded by Actions for each commit. The following 0.1.1 counts are historical, not 0.2.0 results.

## Historical 0.1.1 coverage

The macOS-native smoke tests directly call process identity, display enumeration, Quartz modifier flags, current input-state probes, and frontmost-window probes without sending real desktop input in CI.

0.1.1 Windows portable regression: **27 passed, 5 skipped**; four skips are macOS-only native smoke tests and one is another platform-conditional test; Python syntax checks passed.

- file create/read/binary pagination/replace/backup and stale-write checks;
- symlink mutation rejection;
- overwrite rejection for files with extended attributes;
- Trash failure never falling back to permanent deletion;
- pause marker and audit behavior;
- one-use, expiration, and target validation for observation IDs;
- explicit desktop target locking;
- screenshots not changing the target;
- input rejection after the user switches apps;
- input resuming after returning to the target;
- modal dialogs in the target app;
- rejecting another ordinary window in the same app;
- invalidating locks when process creation identity changes;
- target revalidation between typed characters;
- mouse-up cleanup when a drag is interrupted;
- Quartz-point to screenshot-scale coordinate mapping;
- screenshot operation without an Accessibility dependency;
- explicit Quartz modifier flags for key chords;
- stable-release waiting for user-held modifiers and mouse buttons;
- AXWindowNumber-first window mapping;
- Tunnel identity verification using PID, creation time, and executable path.

GitHub Actions have successfully run the portable suite and macOS native checks, including PyObjC / Quartz / AppKit imports, shell syntax, and the full automated test suite. Version 0.1.1 also checks the newly used Quartz/Accessibility API surface on the macOS runner.

## Pending physical-Mac validation

- Accessibility authorization;
- Screen Recording authorization;
- Quartz screen capture;
- TextEdit / Safari / Finder / VS Code activation;
- real Chinese, emoji, and key-chord input;
- modal sheets/dialogs;
- Retina and multi-display behavior;
- lock screen and fast user switching;
- behavior across macOS 13 / 14 / 15 / 26;
- both Apple Silicon and Intel hardware.

These physical desktop checks remain pending; command regression and CI results do not replace them.

## Security

See [SECURITY.en.md](SECURITY.en.md).
