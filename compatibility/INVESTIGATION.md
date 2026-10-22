# 2026.2.3 事件分发崩溃排查 — 2026-10-22

## 原生崩溃的原因

在当前 Wine 10 / 官方 Windows Cascadeur 2026.2.3 环境中，烟测直接调用
`PySide6.QtCore.QCoreApplication.processEvents()` 会释放 Python GIL。
事件分发期间，宿主原生脚本定时器重入 Python，调用 `PyImport_ImportModule()`，
此时当前 Python 线程状态为空，最终在 `PyImport_Import()` 中访问空指针。
这属于测试手动事件分发与宿主脚本定时器之间的 GIL 重入问题。

原生调用栈的关键路径（偏移相对对应模块）：

```text
QtCore.pyd +0x79257
  Qt event dispatch / QTimer::timerEvent
    presenter_lib +0x168ec6 / +0x1677dd
      py_constr_lib +0x1a00f8
        PyInterpreter::getModuleFunc +0x28
          python311!PyImport_ImportModule
            python311!PyImport_Import +0x39
```

故障指令为 `mov r14, [rax+0x10]`，`RAX=0`。QtCore.pyd 的反汇编及 PE
导入表同时确认：`+0x79245` 调用 `PyEval_SaveThread`，随后调用 Qt 的
`processEvents`，返回后才调用 `PyEval_RestoreThread`。因此崩溃时 GIL
尚未恢复。宿主 `getModuleFunc` 入口到模块导入之间没有获取 GIL。

## 对照复现

从测试安装目录移走 D3D11.dll、工具包脚本目录、Scene Clean 命令目录和
scene_activated 钩子，使用同一份官方宿主与原装 PySide6 做两组测试。
两组均确认 `sys.modules` 中没有 `vmd_bridge` 或 `scripts.vmd_bridge`。

| 测试 | 结果 |
| --- | --- |
| 加载 Cascy.casc，等待 1 秒，调用 PySide processEvents | 同一地址发生原生崩溃 |
| 相同操作，通过 ctypes.PyDLL 调用同一 Qt 函数并保留 GIL | 正常完成 |

复现代码位于 [tests/event_dispatch_probe.py](tests/event_dispatch_probe.py)。
必须在独立测试进程中执行 unsafe 模式，它会刻意重现崩溃。

## 修改范围及结论边界

烟测改为通过 `ctypes.PyDLL` 保留 GIL 分发事件，包括递延删除事件。只修改
测试，不往产品流程加入嵌套事件循环。工具包发布载荷中没有 `processEvents`、
`sendPostedEvents` 或 `QApplication.exec` 调用；现代窗口代码继续保留上游实现。
旧版的菜单回调仍使用正常的 Qt 排队信号/定时器。

另外，原烟测在清理阶段复用已失效的 PySide 主窗口包装器，会产生
`Internal C++ object ... already deleted`。逐步记录原生地址确认：窗口没有
被删除，同一地址的窗口仍可从 Qt 枚举，并具有相同的名称、夹具属性和
CppOwnership；失效的是之前的 Python 包装器。测试因此按原生地址重新取得
窗口进行清理，并断言原窗口仍在、所有插件窗口均已释放。不能简单跳过该错误，
也不能把它当作主窗口实际销毁。增加 CppOwnership 声明本身无法消除包装器失效。

这次原生崩溃无需插件即可复现，不能当作兼容窗口或 D3D11 代理导致崩溃的证据。
也不能仅凭 Wine 下的结果保证原生 Windows 所有交互功能均通过；完整 GUI、
原生安装提权、文件选择器和用户具体 PMX/VMD 工程仍有各自的验证范围限制。

## 独立的脚本扫描告警

继续检查日志发现 7 条可稳定复现的模块导入错误：4 条找不到 `cascadeur_vmd`，
3 条找不到 `vmd_bridge`。宿主在菜单 install() 回调之前扫描辅助模块，而依赖
路径直到 install() 才初始化；`gen_controller_bake` 又写死顶层包名，无法在
`scripts.vmd_bridge` 名称下冷导入。

修复将依赖初始化提前到包导入阶段，并让辅助模块在包内使用相对导入；独立脚本
执行仍保留原来的导入分支，不更改动作算法。现代窗口源码保持与上游逐字节一致。

[tests/action_scan_smoke.py](tests/action_scan_smoke.py) 在独立宿主进程中清除
工具包及依赖的导入缓存，使用真实宿主扫描规则重试，防止首次失败后的缓存掩盖
初始化缺陷。2026.2.3 修复前捕获全部 7 条错误，修复后扫描与两种包名的辅助模块
导入均通过，启动日志也不再出现这些错误。
