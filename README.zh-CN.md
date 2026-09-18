# macOS Local MCP

[English](README.en.md) · **简体中文**

让 ChatGPT 在 Chat 模式中也可以通过 MCP 读取本机文件、写入文件、查看屏幕并操作 macOS 桌面。这个仓库与 Windows 版保持尽量一致的 MCP 工具接口，但桌面实现使用 macOS 的 Quartz、Accessibility API 和系统隐私权限。

> **当前状态：experimental。** 文件系统、暂停、审计、一次性截图编号和桌面目标锁已经有自动测试；真实 Mac 上的 Accessibility、Screen Recording、窗口激活、多显示器和真实键鼠输入还没有完成实机验收，因此不要把当前版本视为已验证的生产工具。

## 权限与风险

这是一个**高权限本机工具**。启用后，模型可以在当前 macOS 用户本来拥有的权限范围内读取和修改文件；如果你再授予 Accessibility 和 Screen Recording，它还可以查看屏幕并向普通桌面应用发送鼠标和键盘输入。

你需要明确接受以下风险：

- 文件访问范围接近当前 macOS 用户自己的访问范围，并不是独立沙箱；
- **Accessibility** 允许宿主进程控制其他普通应用的界面，是高权限授权；
- **Screen Recording** 允许宿主进程读取其他应用窗口和屏幕内容，其中可能包含聊天、邮件、登录页面、文件名和其他私人信息；
- 目标窗口锁、一次性 observation_id、本机暂停、备份和审计只能降低误操作概率，**不能把模型变成低权限进程**；
- 已经发出的键鼠事件和已经完成的磁盘写入无法自动撤销；
- macOS 的 TCC 权限通常授予实际运行 Python/MCP 的宿主（例如 Terminal、iTerm 或其他启动器），授权范围可能比单个 Python 脚本更大；
- 不应把 runtime key、Tunnel 凭据、.local 状态、审计记录或私人截图提交到 GitHub 或粘贴到聊天中；
- 如果你不接受当前用户级文件访问和桌面控制能力，就不应运行这个服务。

建议使用普通用户账号，不以 root 运行；处理密码管理器、支付、敏感账号、医疗/财务信息或重要生产数据时暂停服务。

## 与 Windows 版的接口

主要工具保持相同名称：

| 用途 | 工具 |
| --- | --- |
| 文件信息与目录 | file_info、list_directory |
| 文本与二进制读取 | read_text_file、read_binary_file |
| 创建、覆盖、目录、移动、废纸篓 | write_file、create_directory、move_path、recycle_path |
| 显示器、窗口、截图 | desktop_monitors、desktop_windows、desktop_screenshot |
| 激活窗口并锁定输入目标 | desktop_focus_window |
| 鼠标 | desktop_click、desktop_move、desktop_drag、desktop_scroll |
| 键盘与 Unicode 输入 | desktop_keypress、desktop_type_text |
| 权限状态 | desktop_permissions |
| 状态与暂停 | service_status、service_pause |

坐标使用 **Quartz global points**，不是 Retina 截图中的原始像素。desktop_screenshot 返回 scale_x / scale_y 用于把输出图像坐标换算回桌面坐标。

## 桌面目标锁

桌面输入不会因为重新截图自动跟随用户切换到新的 App。

工作流：

1. 调用 desktop_windows 找到目标窗口；
2. 调用 desktop_focus_window 显式锁定目标；
3. 后续截图只观察，不改变锁；
4. 如果你手动切到其他 App，鼠标、滚轮和键盘输入会被拒绝；
5. 只有再次显式调用 desktop_focus_window 才能切换目标。

目标身份会检查 PID、进程创建时间、可执行文件路径、Bundle ID，以及当前 Accessibility focused window。目标窗口本身允许输入；同一目标 App 的 modal dialog 可以放行；同一 App 中另一个普通窗口不会自动被接管。

每次桌面输入仍要求一个 60 秒内、一次性使用的 observation_id。

## macOS 系统权限

桌面功能需要两类系统权限：

- **Accessibility**：用于激活窗口和发送键鼠输入；
- **Screen Recording**：用于读取屏幕和其他 App 的窗口内容。

服务不会通过 MCP 自动授予这些权限。Permissions.command 只能触发/检查系统权限流程，真正授权必须由本机用户在 **System Settings → Privacy & Security** 中完成。

如果权限被修改，通常需要重启 Terminal / iTerm / 宿主应用以及 MCP 服务。

## 安装

要求：

- macOS 13 Ventura 或更高版本（第一阶段目标）；
- Apple Silicon 或 Intel Mac；
- Python 3.13 或更高版本；
- 可访问 OpenAI 和 GitHub Releases 的 HTTPS 网络。

在真实 Mac 上：

~~~bash
chmod +x *.command
./Setup.command
./Configure.command
./Permissions.command
./Start.command
~~~

Setup.command 会创建独立 .venv、安装 Python 依赖，并按 CPU 架构下载官方 OpenAI Tunnel client。Configure.command 把 Tunnel ID 保存到本地私有状态，把 runtime API key 保存到 macOS Keychain。

常用入口：

~~~text
Control.command      交互式本机控制
Check.command        检查暂停、权限和 Tunnel 状态
Pause.command        本机暂停
Resume.command       本机恢复
Stop.command         停止 Tunnel
~~~

## 文件安全语义

- 覆盖文件需要显式 overwrite=true；
- 覆盖前先保存本地备份；
- expected_modified_ns 可用于检测读后修改；
- symlink 不允许作为变更入口；
- 多硬链接文件、immutable 文件以及带 extended attributes 的文件默认拒绝覆盖，避免原子替换丢失特殊元数据；
- 删除只进入 Trash，失败时不会降级成永久删除；
- 服务源码和 .local 中的凭据、备份、审计不会通过 MCP 文件工具开放。

macOS 的 ACL、File Provider、iCloud、sandbox container 和第三方文件系统语义很多，当前 experimental 版本不会声称覆盖全部特殊元数据场景。

## 测试状态

当前自动化测试覆盖：

- 文件创建、读取、覆盖、备份和并发检查；
- symlink / xattr 等保护；
- pause 和 audit；
- observation_id 单次使用与过期；
- “截图不能重新锁定目标”；
- 用户切换到其他 App 后拒绝输入；
- 切回目标后恢复输入；
- 同一 App 的 modal dialog；
- 同一 App 的另一个普通窗口拒绝；
- 进程重启后旧 target lock 失效；
- 输入过程中每个字符重新检查目标；
- drag 中断后 mouse-up cleanup。

GitHub Actions 会同时运行 portable tests 和 macOS runner 测试，并在 macOS runner 上验证 PyObjC / Quartz / AppKit 可以导入。

**尚未完成的实机验收：** 在真实 Mac 上授权 TCC 后，对 TextEdit / Safari / Finder / VS Code 执行真实截图、窗口切换、中文/emoji 输入、modal dialog、多显示器和锁屏场景。

详见 [VALIDATION.zh-CN.md](VALIDATION.zh-CN.md)。

## 安全边界

这个服务不是 OS sandbox，也不应该以 root 运行。Secure MCP Tunnel 负责远程连接认证；本机 stdio 入口本身应只由受信任的本机客户端或官方 Tunnel 进程调用。

完整安全说明见 [SECURITY.zh-CN.md](SECURITY.zh-CN.md)。

## 官方参考

- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [ChatGPT developer mode](https://developers.openai.com/api/docs/guides/developer-mode)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Apple Accessibility API](https://developer.apple.com/documentation/applicationservices/axuielement_h)
- [Apple Quartz Window Services](https://developer.apple.com/documentation/coregraphics/quartz-window-services)
- [Apple CGPreflightScreenCaptureAccess](https://developer.apple.com/documentation/coregraphics/cgpreflightscreencaptureaccess())
- [PyObjC Quartz notes](https://pyobjc.readthedocs.io/en/latest/apinotes/Quartz.html)

## 许可证

MIT License，详见 [LICENSE](LICENSE)。
