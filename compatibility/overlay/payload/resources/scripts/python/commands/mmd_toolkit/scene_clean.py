# -*- coding: utf-8 -*-
"""cascadeur MMD toolkit -> Scene Clean (official commands entry).

Registers under Scripts menu group "cascadeur MMD toolkit" via the official
python_actions_rule dotted-name convention. All real work lives in the
product package (scripts.vmd_bridge.scene_clean) so the same code is
exercised by offline unit tests.
"""


def name():
    return "cascadeur MMD toolkit.Scene Clean"


def description():
    return ("Restore every MMD model in the current scene to its just-imported "
            "state: reset the initial pose and delete all generated rigs so "
            "bindings can be re-generated. / 将场景中所有 MMD 模型还原到刚导入"
            "状态：复位初始姿势并删除生成的全部 rig，便于重新生成绑定。")


def run(scene):
    from scripts.vmd_bridge import scene_clean
    scene_clean.run_scene_clean(scene)


# Cascadeur 2026.1.x discovers these names through commands_rule.py.
command_name = name
command_description = description
