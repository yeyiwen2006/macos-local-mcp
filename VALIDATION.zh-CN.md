# 验证记录

[English](VALIDATION.en.md) · **简体中文**

当前版本为0.2.0。

## 0.2.0 命令回归

新增测试覆盖默认禁用与本机授权、私有环境过滤、MCP 工具注册、参数边界、Unicode 分页与截断，以及在 macOS runner 上实际运行的 argv/cwd/stdin、双管道排空、非零退出、多字节解码、超时、取消、暂停、撤销许可、SIGTERM 不响应时的终止、普通子进程清理、并发与保留数量限制、符号链接入口及 stdio 会话关闭清理。命令测试不要求或自动授予桌面 TCC 权限。

Windows 只运行便携逻辑测试，真实 POSIX 命令与 macOS stdio 测试在该平台跳过；macOS CI 执行真实子进程测试。具体通过数以对应提交的 Actions 结果为准。以下 0.1.1 数据作为历史记录保留，不充当 0.2.0 验证结果。

## 0.1.1 历史验证

0.1.1 Windows portable 回归：**27 项通过，5 项跳过**；其中 4 项为仅在 macOS 上执行的 native smoke tests，另 1 项为平台条件测试；Python 语法检查通过。

macOS native smoke tests 直接调用进程身份、显示器枚举、Quartz modifier flags、当前输入状态与前台窗口探测，但不会在 CI 中发送真实桌面输入。

自动测试覆盖：

- 文件创建、读取、二进制分页、覆盖、备份与 stale-write 检查；
- symlink 变更拒绝；
- extended attributes 文件覆盖拒绝；
- Trash 失败时不永久删除；
- pause marker 与 audit；
- observation_id 的一次性、过期和 target 校验；
- 显式 desktop target lock；
- 截图不改变目标；
- 用户切换到另一个 App 后拒绝输入；
- 切回目标后恢复；
- 目标 App modal dialog；
- 同一 App 的另一个普通窗口拒绝；
- 进程创建时间变化后旧锁失效；
- 文本输入逐字符重新校验；
- drag 中断的 mouse-up cleanup；
- Quartz point / screenshot scale 坐标映射；
- 截图与 Accessibility 权限解耦；
- Quartz 组合键 modifier flags；
- 用户按住修饰键/鼠标时的稳定释放等待；
- AXWindowNumber 优先窗口映射；
- Tunnel PID + 创建时间 + executable 身份核对。

GitHub Actions 已运行 Windows portable tests 与 macOS native tests；macOS runner 已成功完成 PyObjC / Quartz / AppKit 导入、Shell 语法和完整自动测试。0.1.1 还会在 macOS runner 上检查新增的 Quartz/Accessibility API surface。

## 未完成

尚未在真实 Mac 上验收：

- Accessibility 授权；
- Screen Recording 授权；
- Quartz 截图；
- TextEdit / Safari / Finder / VS Code 激活；
- 中文、emoji、组合键真实输入；
- modal sheet/dialog；
- Retina 与多显示器；
- 锁屏与快速用户切换；
- macOS 13 / 14 / 15 / 26 不同版本上的行为；
- Apple Silicon 与 Intel 双架构实测。

这些桌面实机项目仍待验证，不能用命令回归或 CI 结果替代。

## 安全说明

见 [SECURITY.zh-CN.md](SECURITY.zh-CN.md)。
