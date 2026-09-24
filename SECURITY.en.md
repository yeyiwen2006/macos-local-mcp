# Security Policy

**English** · [简体中文](SECURITY.zh-CN.md)

macOS Local MCP can read and modify files within the current macOS user's permissions. With Accessibility and Screen Recording, it can also observe and control ordinary desktop applications. Treat it as a high-trust local tool.

## Primary risks

- current-user file access is not a sandbox;
- Accessibility can control other ordinary applications;
- Screen Recording can expose private content from other applications;
- target locking, pause, backups, and audit logs reduce mistakes but do not provide complete OS isolation;
- already-posted input and completed writes cannot be automatically undone;
- TCC permissions are typically granted to the host application, such as Terminal or iTerm, not just one script;
- do not run the service as root.

## Permission policy

Remote MCP tools only report permission state; they do not grant or bypass permissions. Permissions.command is a local operator entry point, and final approval must happen through System Settings → Privacy & Security.

Without Accessibility, desktop input should fail closed. Without Screen Recording, screenshots should fail closed.

## Optional command execution

The 0.2.0 command tools are disabled until explicitly enabled by the local operator. Commands have the current user's file/network access and the host's existing permissions, with no automatic elevation. Process groups, entry-point path checks and credential-environment filtering are not a sandbox. File/network side effects receive no file-tool backups and cannot be rolled back by cancellation.

An optional Seatbelt (`sandbox-exec`) profile reduces blast radius: `workspace-write` confines writes to the working directory and system temp directories and denies network; `read-only` denies all writes and network. Seatbelt profiles are deny-first but are not a hard security boundary; `sandbox=None` keeps raw current-user permissions. Credential-shaped environment variables (GitHub/AWS/Anthropic/Google/Stripe tokens, SSH agent variables, Tunnel/API keys) are stripped from the child environment in every mode.

Local pause, `service_pause`, or revoked command approval stops owned command groups; `command_cancel` remains available while paused. Normal shutdown cleans up ordinary group members, not deliberately detached/launchd processes or jobs orphaned by force-killing the service. Commands must not bypass protections, resume the service or approve themselves. Audits record job IDs, argument counts, time and results, never command paths, argv, environment values or output contents. Bounded in-memory output may still contain sensitive data and must not be automatically forwarded.

## Secrets and local state

Do not commit:

- .local/
- .env
- runtime API keys
- Tunnel credentials
- macOS Keychain exports
- backups
- audit records
- Tunnel logs
- private screenshots

Configure.command stores the runtime API key in macOS Keychain instead of a plaintext config file.

## Vulnerability reporting

Use GitHub private vulnerability reporting when enabled. Do not paste credentials, local paths, private files, screenshots, or logs into a public issue.

## Physical validation boundary

The project has simulated safety tests and macOS CI, but real physical-Mac GUI/TCC validation is still pending. Validate it with a dedicated test account and non-sensitive data before relying on it.


## Input state and emergency pause

Before desktop input begins, the service checks common modifier keys and mouse buttons to reduce overlap between human input and automation. No global hotkey is registered by default so the project does not add an Input Monitoring permission surface solely for that feature; use the local Pause.command for emergency pause.