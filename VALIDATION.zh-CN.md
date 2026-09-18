# 验证记录

[English](VALIDATION.en.md) · **简体中文**

当前版本：0.1.1 experimental。

## 已完成

当前 Windows portable 回归：**27 项通过，1 项跳过**；Python 语法检查通过。

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

在这些实机项目完成前，仓库保持 experimental 标记。

## 安全说明

见 [SECURITY.zh-CN.md](SECURITY.zh-CN.md)。
