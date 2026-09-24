# macOS Local MCP

**English** · [简体中文](README.zh-CN.md)

Give ChatGPT in Chat mode MCP-based access to local files, file writes, screen viewing, and macOS desktop control. The MCP surface is intentionally close to the Windows version, while the desktop backend uses Quartz, the macOS Accessibility API, and macOS privacy permissions.

Current version: 0.2.0.

## Permissions and risks

This is a **high-privilege local tool**. Once enabled, a model can read and modify files within the permissions of the current macOS user. If you also grant Accessibility and Screen Recording, it can observe the screen and send mouse and keyboard input to ordinary desktop applications.

Important risks and boundaries:

- file access is close to the current macOS user's own access, not an isolated sandbox;
- **Accessibility** is a high-privilege permission that lets the host process control other ordinary applications;
- **Screen Recording** can expose other application windows and screen contents, including chats, mail, signed-in pages, filenames, and other private information;
- target locking, one-use observation IDs, local pause, backups, and audit logs reduce mistakes but **do not turn the model into a low-privilege process**;
- already-posted input events and completed disk writes cannot be automatically undone;
- macOS TCC permissions are usually granted to the actual host running Python/MCP (for example Terminal, iTerm, or another launcher), so the permission scope can be broader than one Python file;
- runtime keys, Tunnel credentials, .local state, audit records, and private screenshots must not be committed to GitHub or pasted into chat;
- if you are not comfortable granting current-user file access and desktop-control capability, do not run this service.

Use a standard non-root user. Pause the service while handling password managers, payments, sensitive accounts, health/financial information, or important production data.

## API parity with the Windows version

The primary tools use the same names:

| Purpose | Tools |
| --- | --- |
| File metadata and directories | file_info, list_directory |
| Text and binary reads | read_text_file, read_binary_file |
| Create, replace, mkdir, move, Trash | write_file, create_directory, move_path, recycle_path |
| Exact-match text editing | edit_text_file |
| Search and verification | search_text, glob_files, file_hash |
| Displays, windows, screenshots | desktop_monitors, desktop_windows, desktop_screenshot |
| Focus a window and lock input | desktop_focus_window |
| Mouse | desktop_click, desktop_move, desktop_drag, desktop_scroll |
| Keyboard and Unicode text | desktop_keypress, desktop_type_text |
| Local command start, output/status and cancellation | command_start, command_poll, command_cancel |
| Permission status | desktop_permissions |
| Status and pause | service_status, service_pause |

Coordinates use **Quartz global points**, not raw Retina screenshot pixels. desktop_screenshot returns scale_x / scale_y for mapping output-image coordinates back to desktop coordinates.

## Local command execution (0.2.0)

Use `command_start` to launch a program, `command_poll` to read output/status, and `command_cancel` to stop a job. No Terminal focus, Accessibility, or Screen Recording permission is needed. Access to TCC-protected files still depends on the host's existing permissions.

Commands are disabled by default. Run `./Enable-Commands.command` on the Mac and type `ENABLE`, or use the `Control.command` menu. `./Disable-Commands.command` revokes approval and stops running command groups. Enabling does not resume a paused service or restart cancelled jobs. Explicit local administration can use `.venv/bin/python -m macos_local_mcp.control enable-commands --accept-command-risk`.

Example `command_start` arguments for an installed Git:

```json
{
  "executable": "/usr/bin/git",
  "arguments": ["--version"],
  "cwd": "/tmp",
  "timeout_seconds": 30
}
```

Poll the returned `job_id` with `command_poll`; pass the same ID to `command_cancel` to cancel it. **Starting is not success**: only `state=completed` with `exit_code=0` is successful. Nonzero exits, timeout, pause, cancellation and revoked approval remain distinct outcomes.

`sandbox` selects an optional macOS Seatbelt (sandbox-exec) profile: `workspace-write` allows writes only inside cwd plus system temp directories and denies network; `read-only` denies all writes and network. `sandbox=None` (default) keeps raw current-user permissions. Profiles are deny-first, and the profile file is deleted when the job finishes. Known credential-shaped environment variables (GitHub/AWS/Anthropic/Google/Stripe tokens, SSH agent sockets, Tunnel/API keys) are stripped from the child environment in all modes.

Executable and cwd must be absolute paths; arguments must be an array. No shell is implicitly inserted, so spaces, semicolons, `$()` and globs are literal. Explicitly authorize a shell such as `/bin/zsh` and its script arguments when pipelines or redirects are required. `environment` can supply build variables; known Tunnel/API credentials and service-private variables are stripped and cannot be overridden. Executable symlink invocation paths are preserved for Homebrew and virtual environments.

At most 4 jobs run concurrently and 32 jobs are retained in memory. Timeout defaults to 600 seconds and accepts 1–86400. stdout/stderr are incrementally decoded and capped at 262144 Unicode characters each; pipes keep draining after truncation. Polling returns at most 65536 characters per stream. Offsets count characters: follow each stream's `next_offset` and inspect `truncated`. `wait_seconds` is 0–10 and never holds the global action lock. Encodings: UTF-8, GB18030, UTF-16LE and CP1252; invalid byte sequences use replacement characters.

Jobs run in their own POSIX process groups, with stdin at EOF and no interactive terminal, sudo password input or automatic elevation. Normal root exit cleans up remaining children in the group; timeout, cancellation, pause, revoked approval and normal service shutdown also stop the group. Cancellation remains available while paused. **Cancellation is not rollback**; command file writes do not receive `write_file` backups. Deliberately detached processes, launchd-managed processes, and force-killing the MCP process are outside guaranteed cleanup. This is not a daemon manager or an OS sandbox.

Command entry points/cwd reject the service source and private state directories, but arbitrary script internals cannot be isolated by path checks. Never bypass tool refusals, pause, macOS permissions or service protections. Output is memory-only; audit records exclude arguments, environment values, paths and output contents. Output can contain sensitive data and must be treated as untrusted.

## Desktop target lock

Desktop input does not automatically follow the user to a newly foregrounded application after another screenshot.

Flow:

1. find the intended window with desktop_windows;
2. explicitly lock it with desktop_focus_window;
3. later screenshots only observe and do not retarget;
4. if the user switches to another app, mouse, wheel, and keyboard input is rejected;
5. only another explicit desktop_focus_window call changes the target.

The target identity checks PID, process creation time, executable path, Bundle ID, and the current Accessibility focused window. The target window is accepted; a modal dialog in the same target app may be accepted; another ordinary window in the same app is not automatically accepted.

Every desktop input still requires a fresh one-use observation_id that expires after 60 seconds.

## macOS privacy permissions

Desktop features need:

- **Accessibility** for window activation and synthetic input;
- **Screen Recording** for screen and other-application window capture.

The MCP service never grants these permissions remotely. Permissions.command can only request/check the local system workflow. The human must approve permissions in **System Settings → Privacy & Security**.

After changing a permission, restart the Terminal/iTerm/host application and the MCP service as needed.

## Installation

Initial target:

- macOS 13 Ventura or later;
- Apple Silicon and Intel Macs;
- Python 3.13 or later;
- outbound HTTPS access to OpenAI and GitHub Releases.

On a physical Mac:

~~~bash
chmod +x *.command
./Setup.command
./Configure.command
./Permissions.command
./Start.command
~~~

Setup.command creates an isolated .venv, installs Python dependencies, and downloads the official OpenAI Tunnel client for the current CPU architecture, verifying the archive against the release SHA256SUMS.txt (mismatch deletes the download). Configure.command keeps the Tunnel ID in local private state and stores the runtime API key in macOS Keychain.

Useful local controls:

~~~text
Control.command      interactive local menu
Check.command        pause, permission, and Tunnel status
Pause.command        local pause
Resume.command       local resume
Stop.command         stop the Tunnel
Restore.command      browse/restore automatic file backups (local-only)
~~~

## File-safety semantics

- replacing a file requires overwrite=true;
- the original is backed up before replacement;
- expected_modified_ns can reject stale overwrites;
- symlinks are not mutation entry points;
- multiply linked, immutable, and extended-attribute-bearing files are refused by default to avoid losing special metadata during atomic replacement;
- deletion goes to Trash and never falls back to permanent deletion;
- writes, mkdir, move and Trash refuse well-known credential trees (~/.ssh, ~/.gnupg, ~/.aws, ~/Library/Keychains, ~/Library/Cookies) even though reads stay unrestricted;
- move_path falls back to copy-then-Trash across volumes and never overwrites;
- the service source tree and .local credentials/backups/audit state are hidden from MCP file tools, and search_text/glob_files never descend into the state directory.

### edit_text_file (preferred editing primitive)

edit_text_file replaces an exact old_string with new_string, like a patch: the match must be unique (add surrounding lines to disambiguate, or pass replace_all=true), expected_modified_ns rejects stale edits, and the original is backed up automatically. For files up to 8 MiB of UTF-8 it avoids re-sending whole files and is far cheaper and safer than write_file for code changes.

### search_text and glob_files

search_text greps one file or a whole directory tree (case-insensitive by default, opt-in regex, binary files and junk directories such as .git/node_modules are skipped) and returns bounded file/line/text hits. glob_files lists files matching a shell glob. Both never follow directory symlinks and stop at fixed caps (200 hits / 4000 files / 500 matches), so a runaway search cannot flood the context.

### Window-scoped screenshots and input bounds

desktop_screenshot accepts target_window=true to capture only the locked target window, keeping other applications' pixels (private content and untrusted text) out of the model context. Mouse input must land inside the locked window's current bounds; clicking the menu bar or a same-process surface outside the target window is rejected (modal sheets in the target app are exempt because they legitimately extend past the window frame).

macOS has many ACL, File Provider, iCloud, sandbox-container, and third-party filesystem edge cases. The current version does not claim complete coverage of all special metadata semantics.

## Validation status

Automated coverage currently includes:

- file create/read/replace/backup and stale-write checks;
- edit_text_file uniqueness, replace_all, stale-edit and binary rejection;
- search_text/glob_files bounds, junk-directory and state-directory skipping;
- credential-tree write rejection and cross-volume move fallback;
- symlink/xattr protections;
- pause and audit behavior;
- one-use and expiration behavior for observation IDs;
- screenshots not retargeting input;
- window-scoped capture requires a locked target;
- mouse input rejected outside the locked window bounds;
- rejecting input after the user switches apps;
- allowing input after returning to the target;
- modal dialogs in the target app;
- rejecting another ordinary window in the same app;
- invalidating the target after process restart;
- rechecking the target between typed characters;
- mouse-up cleanup when a drag is interrupted;
- Seatbelt read-only/workspace-write enforcement and profile cleanup (macOS);
- credential environment filtering.

GitHub Actions run portable tests and a macOS runner, with checks for PyObjC / Quartz / AppKit and the native APIs used by this project.

Version 0.1.1 also hardens several real-Mac edge cases:

- screenshots no longer require Accessibility merely to determine the foreground window; with Screen Recording alone, capture can still succeed while input_allowed safely reports false;
- key chords explicitly set Quartz Command / Shift / Control / Option flags, improving reliability for real shortcuts such as Command+C and Command+S;
- before each desktop action starts, the service checks for user-held modifier keys or mouse buttons, waits up to one second, and requires 100 ms of stable release;
- Quartz windows are matched to Accessibility windows using AXWindowNumber when available, with titles used only as a fallback;
- Tunnel stop/status logic verifies PID, process creation time, and executable path, then terminates the verified process tree through psutil to reduce PID-reuse risk;
- the absence of a global pause hotkey is deliberate: it avoids adding an Input Monitoring permission surface. Use the local Pause.command for emergency pause; service_pause also remains available to the authenticated MCP caller.

**Still pending physical-Mac validation:** real TCC authorization, screenshots, TextEdit/Safari/Finder/VS Code window switching, Chinese/emoji input, modal dialogs, multi-display behavior, and lock-screen behavior.

See [VALIDATION.en.md](VALIDATION.en.md).

## Security boundary

This service is not an OS sandbox and should not run as root. Secure MCP Tunnel authenticates the remote connection; the local stdio entry point should only be used by a trusted local client or the official Tunnel process.

See [SECURITY.en.md](SECURITY.en.md).

## Official references

- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [ChatGPT developer mode](https://developers.openai.com/api/docs/guides/developer-mode)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Apple Accessibility API](https://developer.apple.com/documentation/applicationservices/axuielement_h)
- [Apple Quartz Window Services](https://developer.apple.com/documentation/coregraphics/quartz-window-services)
- [Apple CGPreflightScreenCaptureAccess](https://developer.apple.com/documentation/coregraphics/cgpreflightscreencaptureaccess())
- [PyObjC Quartz notes](https://pyobjc.readthedocs.io/en/latest/apinotes/Quartz.html)

## License

MIT License. See [LICENSE](LICENSE).
