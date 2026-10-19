# cascadeur MMD toolkit 1.0

![cascadeur MMD toolkit 1.0 release cover](docs/images/01-cover.png)

面向 Cascadeur 的 MMD 骨骼动画工具集，支持 VMD 导入、VMD 导出和生成 Rig 清理。

An MMD skeletal animation toolkit for Cascadeur, with VMD import, VMD export and generated-rig cleanup.

**[下载完整安装包 Download ZIP](https://github.com/BrianFinch-1/cascadeur-mmd-toolkit/releases/download/v1.0/cascadeur-MMD-toolkit-1.0.zip)** · **[中英使用教程 PDF User Guide](https://github.com/BrianFinch-1/cascadeur-mmd-toolkit/releases/download/v1.0/User-Guide.zh-en.pdf)** · [全部发布 Releases](https://github.com/BrianFinch-1/cascadeur-mmd-toolkit/releases)

请下载上方安装包；GitHub 自动生成的 Source code 压缩包只包含此发布仓库的说明和文档，不是插件安装包。

Use the installation ZIP above. GitHub's automatic Source code archives contain only this distribution repository's documentation, not the plugin installer.

## 功能 Features

- **Import VMD**：选择已识别的 MMD 人物或受支持道具，将 VMD 骨骼动作写入时间轴。一次选择多个模型时，它们共用同一份 VMD。Import skeletal motion into detected characters or supported props. Multiple models selected together share the same VMD.
- **Export VMD**：从场景实际骨骼运动导出，人物可根据骨架条件选择 FK 或 IK；多模型分别输出。Export evaluated skeletal animation, with FK/IK choices where supported and separate files for multiple models.
- **Scene Clean**：在当前帧复位检测模型的控制器，再移除生成 Rig，保留网格、骨架和 Armature。Reset controls at the current frame and remove generated rigs while retaining meshes, skeletons and armatures.

## 安装 Install

1. 完整解压下载的 ZIP。Extract the entire ZIP.
2. 关闭准备安装插件的 Cascadeur。Close the Cascadeur installation you intend to update.
3. 双击 **Install.cmd**。Double-click **Install.cmd**.
4. 粘贴直接包含 **cascadeur.exe** 的安装根目录并按 Enter，例如 `C:\Program Files\Cascadeur`。Paste the installation root containing **cascadeur.exe** and press Enter.
5. 如有管理员权限提示，核对路径后允许。等待安装成功，保留备份目录，再重新启动 Cascadeur。Allow administrator access if requested after checking the path. Wait for success, keep the backup path and restart Cascadeur.

安装窗口在成功、失败、取消后均保持显示，按提示按键关闭。需要恢复安装前文件时，关闭对应 Cascadeur，双击 **Restore.cmd** 并输入原备份目录。

The console remains open after success, failure or cancellation. To restore previous installation files, close Cascadeur, run **Restore.cmd** and enter the original backup directory.

## 使用 Use

- 导入：**File → Import → Import VMD**，选择模型，再选择 VMD。Import: choose the model, then the VMD.
- 导出：**File → Export → Export VMD**，选择模型、可用的 FK/IK 策略及输出位置。Export: choose models, an available strategy and a destination.
- 清理：**Scripts → cascadeur MMD toolkit → Scene Clean**。执行前保留工程副本，确认窗口中列出的目标范围。Keep a project copy and review the confirmation before cleaning.

先准备好 MMD 模型、骨架和有效控制绑定，并打开具有已保存路径的 `.casc` 工程。此工具不会自动为任意网格制作人物 Rig。

Prepare the MMD model, skeleton and valid control bindings, then open a `.casc` project with a saved path. The toolkit does not automatically rig arbitrary meshes.

导入选区的起点对应 VMD 第0帧，不会变速拉伸。例：选中100–160帧，会导入源0–60帧。未选区时从目标0帧开始。导出将所选片段重新编号为0帧起，按30 fps约定处理。

The import range starts at source VMD frame 0 without time stretching. Selecting target frames 100–160 imports source frames 0–60. With no selection, import starts at target frame 0. Export renumbers the selected clip from 0 and follows a 30 fps convention.

## 界面预览 Interface previews

模型选择与绑定信息 / Model selection and binding details

![Model picker](docs/images/02-model-picker.png)

人物FK/IK导出策略 / Character export strategy

![FK and IK export strategies](docs/images/03-export-strategy.png)

Scene Clean执行前确认 / Confirmation before removing generated rigs

![Scene Clean confirmation](docs/images/04-scene-clean.png)

## 注意 Notes

- 当前发布面向 Windows x64，并依赖 Cascadeur 提供的 CPython 3.11、Qt 6、PySide6、NumPy和相应脚本能力。安装器检查实际所需组件。This release targets Windows x64 and checks required host components and scripting capabilities.
- 主要范围为骨骼动画和必要 IK 状态；不导出表情、相机或灯光。Export covers skeletal animation and necessary IK states, not morphs, cameras or lights.
- 不同模型的层级、比例、初始姿势和附加变换会影响动作效果。新模型先测试短片段，再检查手指、膝盖、脚踝及脚部接触。Model differences affect playback; test a short clip and inspect the result.
- Scene Clean 会改变工程并移除生成控制器，不是每次导入/导出后的必做步骤。Scene Clean changes the project and is optional, not a routine post-export requirement.
- 操作期间不要切换工程、改绑骨架或编辑动画。出现部分成功/部分动画提示时，按报告逐模型检查。Avoid scene edits during processing and inspect partial-result reports.

## 异常反馈 Report a problem

请联系发布者，说明插件版本、Cascadeur版本和复现步骤，并附上：**出现报错的CASC工程、该模型原版PMX、对应VMD，以及完整报错截图、JSON报告和日志**。请保留原始故障文件，便于重现。

Contact the author with the toolkit version, Cascadeur version and reproduction steps. Include the **failing CASC project, original PMX model, relevant VMD, full error screenshots, JSON reports and logs**.

日志与报告位于 `%LOCALAPPDATA%\cascadeur MMD toolkit`：导入报告在 `bake_work`，导出报告在 `export_reports`；主要日志为 `toolkit.log`、`toolkit-native.log` 和 `toolkit-flow-trace.jsonl`。优先提供报错窗口显示的具体报告文件。

Logs and reports are under the directory above. Prefer the exact report identified by the error window.

本仓库仅用于公开发布用户交付文件及文档，独立于开发仓库。运行依赖的第三方许可见 [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt)。

This repository distributes user packages and documentation independently of the development repository. See the included third-party notices.
