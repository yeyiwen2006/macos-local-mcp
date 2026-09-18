# Validation Notes

**English** · [简体中文](VALIDATION.zh-CN.md)

Current version: 0.1.1 experimental.

## Completed automated coverage

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

The repository remains experimental until these physical-Mac checks are completed.

## Security

See [SECURITY.en.md](SECURITY.en.md).
