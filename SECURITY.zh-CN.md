# 安全说明

[English](SECURITY.en.md) · **简体中文**

macOS Local MCP 可以在当前 macOS 用户权限范围内读取和修改文件；获得 Accessibility 和 Screen Recording 后，还能查看并操作普通桌面应用。因此应把它视为高信任级别工具。

## 主要风险

- 当前用户级文件权限不是沙箱；
- Accessibility 可控制其他普通应用；
- Screen Recording 可暴露其他应用的私人内容；
- 目标锁、暂停、备份与审计只能降低误操作风险，不能形成完整 OS 隔离；
- 已经发送的输入和已经完成的文件写入无法自动撤销；
- TCC 权限通常授予宿主应用，如 Terminal 或 iTerm，而不只是单个脚本；
- 不应以 root 运行。

## 权限原则

MCP 工具只读取权限状态，不远程触发或绕过授权。Permissions.command 是本机操作入口，最终授权必须由用户通过 System Settings → Privacy & Security 完成。

如果没有 Accessibility，桌面输入应拒绝；没有 Screen Recording，截图应拒绝。

## 可选命令执行

0.2.0 的命令工具默认关闭，只能由本机用户明确启用。命令拥有当前用户的文件、网络及宿主已有权限，不自动提权；独立进程组、入口路径校验和凭据环境过滤不是沙箱。脚本可产生文件或网络副作用，这些副作用不享受文件工具备份，也不能靠取消回滚。

`Pause.command`、`service_pause` 或撤销命令许可会要求终止运行中的命令组；`command_cancel` 在暂停期间仍可用。正常关闭会清理组内子进程，主动脱组、launchd 或强制杀死服务的情形不保证清理。不得通过命令改写服务保护、解除暂停或自行批准权限。审计只记录任务标识、参数数量、时间及结果，不记录命令路径、参数、环境值或输出正文。输出按流有界保留在内存，可能包含敏感内容，不应自动转发。

## 凭据与本机状态

不要提交：

- .local/
- .env
- runtime API key
- Tunnel 凭据
- macOS Keychain 导出内容
- 备份
- 审计记录
- Tunnel 日志
- 私人截图

runtime API key 由 Configure.command 写入 macOS Keychain，而不是明文配置文件。

## 漏洞报告

如果仓库启用了 GitHub Private vulnerability reporting，请使用该渠道。不要在公开 Issue 中粘贴凭据、本地路径、私人文件、截图或日志。

## 实机验证边界

当前版本已有模拟安全测试和 macOS CI，但真实 Mac GUI/TCC 流程还没有完成实机验收。正式使用前应在隔离测试账号和无敏感数据环境下完成验证。


## 输入状态与紧急暂停

开始发送桌面输入前，服务会检查常见修饰键和鼠标按钮是否正由用户按住，避免人工操作与自动化操作叠加。全局热键没有默认注册，这是为了不额外引入 Input Monitoring 权限；本机紧急暂停使用 Pause.command。