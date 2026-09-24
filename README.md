# macOS Local MCP

[简体中文](README.zh-CN.md) · [English](README.en.md)

**中文：** 让 ChatGPT 在 Chat 模式中也可以通过 MCP 读取本机文件、写入文件、查看屏幕并操作 macOS 桌面。当前版本为0.2.0。

**English:** Give ChatGPT in Chat mode MCP-based access to local files, file writes, screen viewing, and macOS desktop control. Current version: 0.2.0.

**命令行 / Commands:** 新增 `command_start`、`command_poll`、`command_cancel`，可直接运行 Git、构建、测试等本机命令，无需终端焦点。默认关闭，运行 `Enable-Commands.command` 在本机授权；使用当前用户权限，不自动提权，也不是沙箱。可选 Seatbelt 沙箱（`sandbox="workspace-write"` 限定写目录并断网，`"read-only"` 只读）并过滤凭据环境变量。

Opt-in local commands now support start, output/status polling, and cancellation without terminal focus. Enable locally with `Enable-Commands.command`. Commands use current-user permissions without automatic elevation or an OS sandbox. An optional Seatbelt profile (`sandbox="workspace-write"` confines writes to the working directory and denies network; `"read-only"` blocks all writes) plus credential-environment filtering reduce blast radius.

**编辑与搜索 / Editing and search:** 新增 `edit_text_file`（精确 old_string→new_string 补丁式编辑，唯一匹配校验 + 自动备份）、`search_text`（有界 grep）、`glob_files`、`file_hash`；`desktop_screenshot` 支持 `target_window=true` 只截锁定窗口；鼠标输入强制落在锁定窗口边界内。

New tools: `edit_text_file` (exact-match patch editing with uniqueness checks and automatic backups), `search_text` (bounded grep), `glob_files`, `file_hash`; `desktop_screenshot` gains `target_window=true` window-scoped capture; pointer input must land inside the locked window's bounds. Setup.command now verifies the official Tunnel client download against the release SHA256SUMS.

- 中文完整说明：[README.zh-CN.md](README.zh-CN.md)
- Full English documentation: [README.en.md](README.en.md)
- 安全说明 / Security: [SECURITY.zh-CN.md](SECURITY.zh-CN.md) · [SECURITY.en.md](SECURITY.en.md)
- 验证记录 / Validation: [VALIDATION.zh-CN.md](VALIDATION.zh-CN.md) · [VALIDATION.en.md](VALIDATION.en.md)
- License: MIT

## 权限与风险 / Permissions and risk

**中文：** 这是高权限本机工具，不是操作系统沙箱。文件工具拥有当前 macOS 用户本来具有的文件权限；授予 **Accessibility** 后宿主进程可以控制普通应用，授予 **Screen Recording** 后可以读取屏幕和其他应用窗口内容。macOS 的 TCC 权限通常授予实际运行 MCP 的 Terminal、iTerm 或其他宿主，因此授权范围可能大于单个 Python 脚本。目标锁、暂停、备份和审计只能降低误操作风险。处理密码管理器、支付、敏感账号、医疗/财务信息或重要生产数据时应暂停服务。

**English:** This is a high-privilege local tool, not an operating-system sandbox. File tools operate with the current macOS user's file permissions. Granting **Accessibility** lets the host process control ordinary applications, while **Screen Recording** lets it observe screen and window contents. macOS TCC permissions are generally granted to the actual Terminal/iTerm/host process running MCP, so the permission scope can be broader than one Python script. Target locking, pause controls, backups, and audit logs reduce mistakes but do not create a low-privilege boundary. Pause the service around password managers, payments, sensitive accounts, health/financial information, or important production data.

See [SECURITY.zh-CN.md](SECURITY.zh-CN.md) / [SECURITY.en.md](SECURITY.en.md) for details.
