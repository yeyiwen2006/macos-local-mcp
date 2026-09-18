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

## Current experimental boundary

The project has simulated safety tests and macOS CI, but real physical-Mac GUI/TCC validation is still pending. Validate it with a dedicated test account and non-sensitive data before relying on it.


## Input state and emergency pause

Before desktop input begins, the service checks common modifier keys and mouse buttons to reduce overlap between human input and automation. No global hotkey is registered by default so the project does not add an Input Monitoring permission surface solely for that feature; use the local Pause.command for emergency pause.