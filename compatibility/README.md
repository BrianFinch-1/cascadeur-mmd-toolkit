# Cascadeur 2026.1.3 compatibility revision 2

这是基于 v1.0 **完整发布 ZIP** 的兼容修订。原始 v1.0 下载不会自动变化。

安装方式仍为完整解压 ZIP → 关闭 Cascadeur → `Install.cmd` → 输入安装根目录。
恢复使用原备份目录和 `Restore.cmd`。本修订仍面向 Windows x64。

旧版缺少的组件并非只需取消安装检查：2026.1.3 的定制 Qt 6.5.3 还缺少官方
QtGui/QtQuick 绑定需要的导出符号，并且没有新版命令注册规则和脚本服务器。
本修订补齐匹配的 QtCore/QtNetwork/QtQml、Shiboken 与 CPython stable ABI
转发器，通过原有 QML 引擎直接处理菜单回调，不向旧版安装 D3D11 代理。
窗口枚举使用宿主导出的 `allWindows()`；小型 C DLL 仅负责原子释放返回列表
的引用，源码在 [native/qt_list_ref.c](native/qt_list_ref.c)。

新版继续使用宿主绑定和原生回调路径；构建器从固定上游 ZIP 逐字节保留现代窗口实现，
只有旧版加载独立的 `legacy_dialogs.py`。安装器在写入前核对全部必要的 PE 导出，
并拒绝覆盖旧版中未知/残缺的绑定。新增文件全部进入既有安装事务和恢复日志。
同时移除了把 Qt 内联 `topLevelWindows()` 当作必须 DLL 导出的错误检查，
仍要求实际导出的 `allWindows()`。

构建：

```sh
python -m pip install -r compatibility/build-requirements.txt
python compatibility/build_release.py --cache downloads --output dist
```

构建器校验固定 SHA256 的原始发布包、官方 PyPI wheel 和 CPython 压缩包，
应用 `overlay/`，编译原子引用帮助 DLL，并重建文件清单与发行 ZIP。不会打包
Cascadeur 的 Qt DLL、插件、QML 树或完整 Python 解释器。首次构建需要联网，
输入文件缓存齐全后可以离线构建。产物是
`cascadeur-MMD-toolkit-1.0-2026.1.3-compat-r2.zip` 和 `SHA256SUMS.txt`。

r2 修复恢复后仅剩正常 Python 缓存导致再次安装被拒绝的问题；保留缓存，仍拒绝
未知绑定和未知缓存。安装器读取 cascadeur.exe 的实际版本号：2026.1.3 起选择
legacy，2026.2.0 起选择 native，再核对相应接口能力；无法识别的版本、低于
2026.1.3 或旧版混入新版脚本规则会在写入前被拒绝。构建排除开发缓存，并在
Python 优化模式下也执行发布文件和运行库的完整性检查。
另修复宿主扫描脚本早于 install() 时依赖路径尚未初始化，以及辅助模块写死
包名的问题；包内相对导入支持两种宿主包名，并保留原独立脚本导入路径。

构建回归测试：

```sh
python compatibility/tests/test_build_release.py --cache downloads
```

原生 Windows 安装事务测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File compatibility/tests/installer_transactions.ps1 `
  -ReleaseRoot 'C:\build\cascadeur MMD toolkit 1.0' -HostRoot 'C:\Cascadeur-2026.1.3'
```

宿主测试：先将对应模式的安装文件部署至独立测试安装，再运行：

```powershell
cascadeur.exe -c 'import os; os.environ["MMD_SMOKE_OUTPUT"]="C:/test/result.json"; exec(open("C:/repo/compatibility/tests/host_smoke.py", encoding="utf-8").read())'
```

测试会读取自带 Cascy 场景，在宿主 QGuiApplication 中创建独立的真实 QML
窗口/菜单，验证旧命令发现、289 对象/66 骨骼读取、重复菜单安装、排队回调、
菜单重建、模型选择、确认窗口、导出策略与进度窗口；不保存示例场景。

`tests/action_scan_smoke.py` 另在独立进程中使用 `MMD_SCAN_OUTPUT` 记录真实
宿主命令/脚本扫描与两种包名的辅助模块冷导入。测试会清空本工具包的导入缓存，
应在独立测试安装的命令模式中运行。`tests/event_dispatch_probe.py` 提供
GIL 崩溃的无插件宿主对照，默认使用安全分发；unsafe 模式仅用于刻意重现故障。

已完成的事务测试包括预览无写入、重复安装、绑定冲突保护、修改文件恢复保护、
精确恢复已有文件与新增目录、缓存残留后的重装、版本/接口不一致拒绝，
以及中途写入失败完整回滚。当前自动验证使用
Linux/Wine 的官方 Windows 宿主和 Linux PowerShell；后者只对路径和原生 PE
版本访问使用测试适配器，未执行 Windows PowerShell 5.1/UAC 实机安装。
完整交互界面及用户具体 PMX/VMD 工程的导入导出仍需 Windows 实机回归。

`overlay/` 只保存相对原发布包发生改变或新增的源码/通知。原发布的其余代码、
VMD 算法和数据仍由固定校验和的上游 ZIP 提供。

详细结果与范围见 [VALIDATION.md](VALIDATION.md)。新版原生崩溃已通过无插件
宿主的对照定位到烟测事件分发释放 GIL 的问题；证据和测试修正见
[INVESTIGATION.md](INVESTIGATION.md)。产品不增加嵌套事件循环。
