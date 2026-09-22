#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jev_workflow_check.py — 用 TypeSafe 的 Jev（System One 模型）检查 QTVictory
文档治理工作流的状态。

设计原则（分层，遵循 TypeSafe "代码掌流程、模型给语义判断" 的指引）：
  · 确定性采集交给代码：解析变更卡/todo/CHANGELOG/design 头部、最近提交，
    得到"事实"（facts）。查表、计数、状态比对本就是代码擅长的硬逻辑。
  · 语义判定交给 Jev：把「项目文档治理流程」+「当前采集到的状态」作为 state，
    用 typed questions（Choice / Noul）让 Jev 判断——
    当前处于治理流哪个阶段、双向同步是否完成、零沉淀纪律是否被破坏、整体合规度。
    这些"对照规则做解读"的判断，正是 Jev 这类决策模型的价值所在。

每次调用本脚本即重复上述动作。

用法：
  # API Key 获取顺序：环境变量 TYPESAFE_API_KEY → ~/.config/typesafe/credentials.env
  # （路径可用 TYPESAFE_CREDENTIALS_FILE 覆盖；key 值不会出现在任何输出中）
  export TYPESAFE_API_KEY=sk-...
  python3 scripts/jev_workflow_check.py                 # 采集 + 调用 Jev + 解读
  python3 scripts/jev_workflow_check.py --json          # 只打印将发给 Jev 的请求体,不调用
  python3 scripts/jev_workflow_check.py --offline       # 只采集状态并打印事实,不调用 Jev
  #   --offline 只做确定性采集与代码侧硬判，双向同步 / 零沉淀等语义判定被跳过，
  #   收口前请联网重跑本脚本完成自检（红线 7）。
  python3 scripts/jev_workflow_check.py --api-key sk-.. # 命令行传 key；⚠ 会出现在 ps 等
  #    进程列表中，非交互场景建议改用环境变量或 credentials 文件

退出码：0 正常；2 缺 key；3 采集或网络/API 失败；4 检测到治理违规（红线 7 门禁：存在违规不得合入主干）；5 Jev 响应无效（自检未完成，须修复后重跑）；6 语义判定不确定或置信不足（结论仅供参考，须人工核对采集事实后决策；人工确认前不得视为已完成自检）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
HTTP_TIMEOUT = 45  # 秒

# 置信门控阈值：低于该值则该判定降级为参考意见、不作为硬判据。
CONFIDENCE_GATE = 0.60
# Noul 概率距 0.5 小于该值视为"不确定"：展示层据此标注，门禁层也据此
# 放过（转人工复核），两层必须同源，否则会出现答案行写「不确定」而结论行
# 写确定性违规的自相矛盾输出。
#
# 带宽取 0.25 而非更窄的值，依据是同一输入的实跑观测：干净仓库连续 4 次
# 实跑 P(yes)=0.33/0.36/0.37/0.42，真实沉淀违规实跑 P(yes)=0.06。若按
# 0.15 设带（下沿 0.35），干净仓库的噪声会横跨边界，使门禁退化成抛硬币
# ——把干净检查点判成 exit 4，正是运营者学会忽略退出码的开端。0.25 的下沿
# 落在观测到的「干净噪声上界 0.42」与「真实违规 0.06」之间的空档中部。
NOUL_UNCERTAIN_BAND = 0.25

# 阶段 Choice 选项 -> 人类可读标签
STAGE_LABELS = {
    "idle": "空闲 · 无进行中变更",
    "awaiting_verification": "等待核验 · 存在待核验变更卡",
    "awaiting_bidirectional_sync": "等待双向同步 · 已核验通过但回链/CHANGELOG 未闭环",
    "awaiting_merge_or_release": "等待合入/发布 · 已核验通过且已同步",
    "has_violation": "存在治理违规",
}

# 合规五档（单一数据源），自最差到最好排列：
#   (档位标签, 代表值, 判档依据)
# 用 Choice 型而非 Score 型的实证理由：Score 型下 Jev 反复按 1~5 里克特刻度
# 给分（三次实跑 2.40/2.43/2.48），与声明的 [0,1] 刻度对不上；越界回填会把
# 「中等」误显示成「完全符合治理流程」。改由模型直接选档、代码映射代表值，
# 刻度歧义随之消失。代表值仅供阈值比较与展示，不要求模型产出该数值。
COMPLIANCE_BANDS = (
    ("存在明确违规", 0.20,
     "任一受控枚举被破坏（状态/类型非法）、双向同步点断裂、或 todo 零沉淀纪律被破坏——以 current_state.code_assertions 为证"),
    ("有关键环节缺失或存疑", 0.50,
     "治理链路上有关键环节无证据可依，或证据互相矛盾，无法判定已闭环"),
    ("基本合规，轻微瑕疵", 0.70,
     "主链路合规，仅存不影响闭环的轻微瑕疵（如文案、编号格式、描述截断）"),
    ("整体合规，个别待办", 0.90,
     "全部同步点已闭环，仅剩常规待办：已核验通过尚未合入主干、或尚未打版本 tag"),
    ("完全符合治理流程", 1.00,
     "所有 C 卡均已核验通过、双向同步闭环且已合入主干，todo 零沉淀，无任何待办"),
)
COMPLIANCE_BAND_OF = {band[0]: band[1] for band in COMPLIANCE_BANDS}
# 红线 7 门禁阈值：低于「基本合规，轻微瑕疵」档即阻断合入。
# 取 0.70 而非 0.40 的理由：「有关键环节缺失或存疑」意味着关键环节无证据可依或
# 证据互相矛盾，按红线 7 即属「存在治理违规」；而 0.90 / 1.00 两档的判档依据
# 已把「已核验通过尚未合入」「尚未打 tag」明文列为常规待办，属于应当放行的状态。
# 方向取严：宁可误拦（人工复核后可放行），不可漏放（静默合入正是红线 7 要防的
# 核心风险）。
COMPLIANCE_VIOLATION_BELOW = 0.70


def _is_num(v) -> bool:
    """真数值判断。bool 是 int 子类，须显式排除，避免 true/false 混入数值门禁。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def compliance_band_value(label):
    """把合规档位标签映射为代表值；标签不在受控档位内时返回 None。"""
    return COMPLIANCE_BAND_OF.get(label)


# ---------------------------------------------------------------------------
# 要"告诉 Jev"的项目文档治理流程（来自 AGENTS.md 与 docs/README.md §3）
# 这是本脚本最重要的输入：让 Jev 知道该拿什么规则去评判当前状态。
# ---------------------------------------------------------------------------

GOVERNANCE_PROCESS = {
    "project": "QTVictory — A 股实时前向仿真模拟交易系统（私人单机自部署）",
    "two_entry_flows": {
        "bug_fix": (
            "Bug 修复/回调/参数/接口微调流：① 在 docs/devel/todo/ 对应版本表登记；"
            "② 在 docs/devel/change/ 复制 template.md 建 C00x 卡（编号只增不插）；"
            "③ 立即从 todo 表格物理删除对应行（零沉淀纪律）；"
            "④ 改代码并补回归测试，跑测试命令；"
            "⑤ 涉及设计规则时同步修订 docs/devel/design/ 对应章节；"
            "⑥ AI 执行测试与实测后在会话向人工汇报事实，人工确认后由 AI 代签收口"
            "（卡状态 待核验 → 核验通过/核验驳回）；"
            "⑦ 核验通过后才允许合入主干；⑧ 双向回写闭环。"
        ),
        "feature_design": (
            "新功能/新 Phase 立项流：① todo/future.md 登记方向；"
            "② docs/devel/design/ 新增或修订章节（头部状态以『讨论中』起步，评审通过后改『现行基线』）；"
            "③ docs/devel/plan/ 建 M 卡、docs/devel/task/ 建 T 卡（Phase 2 起才允许）；"
            "④ 开发；⑤ 测试；⑥ docs/devel/report/ 验收（结论 通过/受限通过/未通过）；"
            "⑦ 收口冻结 T 卡、同步 CHANGELOG 与版本号、打 git tag。"
        ),
    },
    "bidirectional_sync_points": [
        "design/ 对应章节原位增补反向引用标签（> 📌 关联变更: [C00x]...）",
        "design/ 头部『关联变更』追加 C 编号；文末变更记录增补条目并回链 C 卡",
        "design/ 版本号：纯勘误/措辞/格式 +0.1；业务规则/接口契约/行为语义 +1.0",
        "CHANGELOG.md 按 semver 记账，条目带 [C00x] 超链接并与 C 卡双向互链",
        "C00x 变更卡收尾：AI 汇报实测、人工会话确认、AI 代签（记录确认要点与纳入版本号）",
    ],
    "change_card_type_enum": ["BugFix", "Rollback", "Refactor", "Param"],
    "change_card_status_enum": ["待核验", "核验通过", "核验驳回"],
    "design_status_enum": ["现行基线", "讨论中", "已废弃"],
    "zero_sediment_rule": (
        "todo 事项一旦落入 change/（建 C 卡）或 design/（更新基线），"
        "必须立即从 todo 表格物理删除，不留 [x] 历史勾选；闭环与审计由 change/design 承载。"
        "todo 行的『拟流转目标』列为受控枚举：change（BugFix/Rollback/Refactor/Param）/ design /"
        " plan/task / report/test，是事项打算落入哪条流的唯一机器可读键。"
    ),
    "merge_gate": "核验通过后才允许合入主干；CHANGELOG 版本条目合入主干时打对应 vX.Y.Z tag。",
    "context_only_rules": {
        "anchor_discipline": (
            "章节号只增不插中间；废弃章节原位保留并标注 [已废弃]，编号不复用；"
            "跨文档引用优先『文档 + 版本 + 节号』三元组。"
        ),
        "metadata_contract": (
            "文档头部引用块：**键名**: 值 ｜ 键值，半角冒号加单空格、全角竖线分隔；"
            "状态枚举纯净（禁括号小尾巴）；日期 ISO YYYY-MM-DD。"
            "（其中『状态枚举纯净』一项已由 code_assertions.illegal_status 强制执行，此处仅作背景。）"
        ),
        "report_conclusion_enum": ["通过", "受限通过", "未通过"],
    },
}


# 发给 Jev 的 typed questions（一次 fan-out，互不依赖、并行求值）
QUESTIONS = {
    "current_stage": {
        "type": "choice",
        "instructions": (
            "根据 `governance_process.two_entry_flows.bug_fix` 定义的变更核验流，"
            "判断 `current_state` 目前整体处于哪个阶段。五个选项**互斥且有序**，"
            "请自上而下命中第一个成立的条件即止，不要跳序：\n"
            "① `has_violation`：`code_assertions` 的 `illegal_status` /"
            " `illegal_type` / `sediment_violations` 任一非空，或 `frozen_dir_dirty`"
            " 为 true（代码硬判，直接采信）；\n"
            "② `awaiting_verification`：`code_assertions.pending_cards` 非空；\n"
            "③ `awaiting_bidirectional_sync`：存在 核验通过 的卡，但"
            " `governance_process.bidirectional_sync_points` 仍有同步点未闭环——以"
            " `latest_verified_card`、`design_docs[].inplace_backlinks`、`changelog` 为证；\n"
            "④ `awaiting_merge_or_release`：`code_assertions.unmerged_cards` 非空，"
            "即已核验通过且同步完成、但「关联提交」仍为『待提交』尚未合入主干；\n"
            "⑤ `idle`：以上皆不成立——所有卡均已核验通过、同步闭环且已合入。\n"
            "注意：`pending_cards` 与 `unmerged_cards` 只是**阶段判别器**，不是违规字段，"
            "它们非空时不得选 `has_violation`。"
            "`current_state.git.last_commit` 仅作回写是否落盘的佐证，不作为阶段判别器。"
        ),
        "criteria": {
            "idle": "没有进行中的变更：所有 C 卡均已 核验通过、双向同步闭环且已合入主干",
            "awaiting_verification": "存在 待核验 状态的 C 卡（code_assertions.pending_cards 非空）",
            "awaiting_bidirectional_sync": (
                "存在 核验通过 的 C 卡，但双向同步点（design 原位回链 / design 头部关联变更 / "
                "CHANGELOG 互链）尚未全部完成"
            ),
            "awaiting_merge_or_release": (
                "C 卡已 核验通过 且同步完成，但「关联提交」仍为『待提交』"
                "（code_assertions.unmerged_cards 非空），待合入主干或纳入版本打 tag"
            ),
            "has_violation": "存在治理违规：code_assertions 非空（状态/类型非法、应删未删）",
        },
    },
    "pending_verification": {
        "type": "noul",
        "instructions": (
            "是否存在状态为『待核验』的变更卡？"
            "`current_state.code_assertions.pending_cards` 是代码按受控枚举"
            "（`governance_process.change_card_status_enum`）查表得到的确切清单，"
            "直接采信：非空即 true，为空即 false；不要自行翻查 change_cards 全表推翻它。"
        ),
        "criteria": {
            "true": "至少有一张 C 卡状态为 待核验（pending_cards 非空）",
            "false": "没有 待核验 状态的 C 卡（pending_cards 为空）",
        },
    },
    "sync_complete": {
        "type": "noul",
        "instructions": (
            "针对 `current_state.latest_verified_card`（最新一张已 核验通过 的卡），"
            "逐项核对 `governance_process.bidirectional_sync_points` 的同步点。"
            "注意 design/ 的『原位反向引用标签』与『头部关联变更字段』是两个**独立**同步点，"
            "须分别取证：`current_state.design_docs[].inplace_backlinks` 是正文 📌 标签中"
            "提取到的 C 编号列表，`linked_changes` 是头部字段，二者不可互相替代。"
            "另需核对 `current_state.changelog` 是否已登记并互链该卡，"
            "以及该卡 `linked_design` 指向的文档是否确实出现在 `design_docs` 中。"
            "双向同步点第 5 条（AI 汇报实测、人工会话确认、AI 代签、纳入版本号）的取证来源是"
            "`latest_verified_card.checklist_and_signoff_excerpt`——即该卡 §4/§5 正文摘录，"
            "这是它**唯一**的取证入口：该字段为空字符串即视为未取证，判 false；"
            "有内容时再逐条比对四条要义是否都在文中体现。"
            "除该字段外，卡正文其余部分（含 checklist 勾选项、状态自述）只是自述，"
            "不得作为同步已完成的证据。"
        ),
        "criteria": {
            "true": "所有双向同步点均已完成",
            "false": "仍有同步点缺失",
        },
    },
    "zero_sediment_ok": {
        "type": "noul",
        "instructions": (
            "对照 `governance_process.zero_sediment_rule` 判定："
            "`current_state.todo_now` 与 `current_state.todo_future` 中是否"
            "没有『已建 C 卡或已立项、本应被物理删除却仍残留』的事项。\n"
            "取证分两层，代码硬判优先，不要自行翻查全表推翻它：\n"
            "① `current_state.code_assertions.sediment_violations`：行 ID 命中"
            " `current_state.todo_transferred` 流转账本的残留行，非空即判 false；\n"
            "② 其为空时再逐行看 `target_kind`：仅当某行存在**正面落盘证据**——ID 命中"
            " todo_transferred 账本、design 文档的『关联变更』或文末『变更记录』提及同一事项、"
            "或存在同主题 C 卡——才判 false。\n"
            "注意：`target` 列只记录落点意图（如『design 02 §6.1』），该章节可能先于事项存在，"
            "写了落点不等于已落盘；todo 中正常的方向级储备与在办事项不得判 false。"
        ),
        "criteria": {
            "true": "todo 表格无应删未删残留，零沉淀纪律得到遵守",
            "false": "存在已建卡/已立项但仍残留在 todo 的事项",
        },
    },
    "compliance": {
        "type": "choice",
        "instructions": (
            "在下方 criteria 的五档中，为 `current_state` 的整体合规程度选出**唯一**最贴合的一档。"
            "五档按严重度递进、互斥且有序，请自上而下命中第一个成立的条件即止，不要跳序、不要折中取中间档。"
            "**只评判本脚本已取证的范畴**：变更卡状态/类型枚举、双向同步点、todo 零沉淀、"
            "合入门禁；`governance_process.context_only_rules` 中的规则本脚本不采集证据，"
            "不得纳入扣分。todo 中正常的方向级储备与在办事项不得扣分。"
            "判定请直接采信 `current_state.code_assertions`，不要自行翻查全表推翻它。"
        ),
        # 由 COMPLIANCE_BANDS 单一数据源生成；输出层 COMPLIANCE_BAND_OF 与
        # detect_violation 的阈值判定同源映射，三处共用同一份档位定义。
        # API 契约：choice 型的 criteria 必须是「选项 → 判档依据」字典（列表会被 422 拒收）。
        "criteria": {
            label: rubric for label, _value, rubric in COMPLIANCE_BANDS
        },
    },
}

# ---------------------------------------------------------------------------
# noul 题的代码侧元数据
# ---------------------------------------------------------------------------
# 刻意不放进 QUESTIONS：QUESTIONS 会被整体序列化进 API 请求体，而 API 对 question
# 形状有严格校验（实测 choice.criteria 传列表会被 HTTP 422 拒收），附加字段有风险。
# 这些常量只服务代码侧输出与硬判，不进入请求体。
#
# NOUL_LABELS:   题号 → 中文标签，供 print_jev_answers 输出。
# NOUL_QIDS:     全部 noul 题号（含无极性标注者），供 validate_response 做存在性与类型校验。
# NOUL_POLARITY: 题号 → (side, phrase)。side ∈ {"low","high"} 表示代码侧硬判已命中时，
#                该题概率理应偏向的一侧；phrase 是同一事实的可读措辞，与展示层同源。
#                pending_verification 刻意只有标签、没有极性条目：它是阶段判别量而非
#                违规量，它与 current_stage 的矛盾由 cross_check() 负责收口。
NOUL_LABELS = {
    "pending_verification": "存在待核验变更卡",
    "sync_complete": "双向同步点已全部完成",
    "zero_sediment_ok": "todo 零沉淀纪律得到遵守",
}

NOUL_QIDS = tuple(NOUL_LABELS)

NOUL_POLARITY = {
    "sync_complete": ("low", "仍有同步点缺失"),
    "zero_sediment_ok": ("low", "todo 存在应删未删残留"),
}


# ---------------------------------------------------------------------------
# 仓库定位与解析工具
# ---------------------------------------------------------------------------

def find_repo_root() -> Path:
    """定位仓库根：优先脚本上级目录，其次 cwd 及其祖先，要求含 docs/devel/change。"""
    candidates = [Path(__file__).resolve().parent.parent]
    cwd = Path.cwd()
    candidates.extend([cwd, *cwd.parents])
    for base in candidates:
        if (base / "docs/devel/change").is_dir() and (base / "AGENTS.md").is_file():
            return base
    sys.stderr.write("错误：未能定位仓库根（未找到 docs/devel/change 与 AGENTS.md）。\n")
    sys.exit(3)


def trunc(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " …[截断]"


def parse_header_fields(text: str, max_lines: int = 14) -> dict:
    """解析文档头部 `> **键名**: 值 ｜ **键名**: 值` 引用块为字典。"""
    fields: dict = {}
    for line in text.splitlines()[:max_lines]:
        stripped = line.strip()
        if not stripped.startswith(">"):
            continue
        body = stripped.lstrip(">").strip()
        for segment in body.split("｜"):  # 全角竖线分隔
            m = re.match(r"\*\*(.+?)\*\*\s*:\s*(.+)", segment.strip())
            if m:
                fields[m.group(1).strip()] = m.group(2).strip()
    return fields


def section_from(text: str, header_prefix: str, limit: int) -> str:
    """抽取从某个 `## N.` 小节起到文末的文本（用于取核验清单+结论）。"""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(header_prefix):
            start = i
            break
    if start is None:
        return ""
    return trunc("\n".join(lines[start:]), limit)


def card_sort_key(card_id: str):
    m = re.search(r"(\d+)", card_id or "")
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# 状态采集（确定性代码）
# ---------------------------------------------------------------------------

# 变更卡正文的「关联提交」字段：`待提交` 或 `[hash](commit url)`
CARD_COMMIT_RE = re.compile(r"关联提交[：:]\s*`([^`]+)`")


def _normalize_commit(raw: "str | None") -> "str | None":
    """归一「关联提交」取值：commit hash / 待提交 / 其它原值（截断）。

    这是区分「已合入主干」与「待合入」的判别器：值为 commit hash 即已合入，
    为『待提交』即尚未合入。实测 21/22 卡为 hash、C022 为待提交，区分度干净。
    """
    if not raw:
        return None
    value = raw.strip()
    if value == "待提交":
        return "待提交"
    m = re.search(r"([0-9a-f]{7,40})", value)
    return m.group(1) if m else trunc(value, 40)


def _is_commit_hash(value: "str | None") -> bool:
    """判断「关联提交」取值是否已是 commit hash，即该卡是否已合入主干。

    实测 22 张卡的取值形态：`待提交` 或 `[hash](commit url)`；`_normalize_commit`
    已把前者归一成字面量、后者抽成短 hash。这里再兜一层：只要归一后的值本身就是
    一段 ≥7 位十六进制串就算已合入——这样将来出现裸 hash、或
    `abc1234 (squash)` 这类变体写法时，不会因为字面量不等于「待提交」就被
    误判成尚未合入。取不到 hash（None / 待提交 / 其它文案）一律视为未合入，
    方向从严：宁可多等一次合入确认，不可把没合入的卡放行成 idle。
    """
    return bool(re.fullmatch(r"[0-9a-f]{7,40}", value or ""))

def gather_change_cards(repo: Path) -> list:
    cards = []
    change_dir = repo / "docs/devel/change"
    for path in sorted(change_dir.glob("*.md")):
        # README.md（目录说明）与 template.md（卡片模板）都不是变更卡。
        # 用 *.md 全量扫 + 显式排除，而不是 C*.md 前缀匹配：后者会让下面这行
        # 排除变成永远不生效的死代码，且将来出现非 C 前缀命名的卡片时整份漏采。
        if path.name.lower() in ("readme.md", "template.md"):
            continue
        full = path.read_text(encoding="utf-8")
        fields = parse_header_fields(full)
        m = CARD_COMMIT_RE.search(full)
        cards.append({
            "id": fields.get("卡片ID") or path.stem.split("-")[0],
            "type": fields.get("类型"),
            "status": fields.get("状态"),
            "created": fields.get("创建日期"),
            "linked_design": fields.get("关联设计"),
            "linked_commit": _normalize_commit(m.group(1) if m else None),
            "file": str(path.relative_to(repo)),
        })
    cards.sort(key=lambda c: card_sort_key(c["id"]))
    return cards


def latest_verified_card(repo: Path, cards: list) -> dict | None:
    """取最新一张『核验通过』的卡，附上核验清单与结论摘录，供 Jev 核对同步点。

    `checklist_and_signoff_excerpt` 是 §3.3 双向同步点第 5 条
    （C00x 变更卡收尾：AI 汇报实测、人工会话确认、AI 代签、纳入版本号）的**唯一**
    取证来源——design/ 与 CHANGELOG 都承载不了这一条，缺了它该同步点就无证据可依。
    因此读盘失败也返回空串而不是抛异常：单张卡读不了不该让整个自检崩成 exit 1。
    """
    verified = [c for c in cards if c.get("status") == "核验通过"]
    if not verified:
        return None
    latest = verified[-1]
    try:
        full = (repo / latest["file"]).read_text(encoding="utf-8")
    except OSError:
        full = ""
    latest = dict(latest)
    latest["checklist_and_signoff_excerpt"] = section_from(full, "## 4.", 2600)
    return latest


def gather_changelog(repo: Path) -> dict:
    path = repo / "CHANGELOG.md"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^##\s*\[([\d.]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})", text, re.M)
    result = {}
    if m:
        result["version"] = m.group(1)
        result["date"] = m.group(2)
        # 抽取最新版本区块摘录，供 Jev 判断 CHANGELOG 是否已登记最新 C 卡
        start = m.start()
        result["latest_section_excerpt"] = trunc(text[start:start + 1600], 1600)
    return result


# 待办行 ID：BG/EN/FT/TD-编号（4 位）
TODO_ID_RE = re.compile(r"^(BG|EN|FT|TD)-\d{4}$")
# todo 文档「流转纪律」段中的已流转记录：EN-0010 已流转至 [C022](...)
# 一条记录可带多个源事项与多个落点：EN-0002/EN-0003 已流转至 [C002]/[C003]。
# 因此两侧都按分隔符切片，由 gather_todo 按位配对——早先只取单个 ID 的写法
# 会把复合记录解析成「EN-0003 => C002」：EN-0002 整条漏记、EN-0003 错配到 C002，
# 两条应删未删的残留行同时从 sediment_violations 里消失。
# 连字符取可选：另需兼容遗留的无连字符形态（C001 已流转至 [C001]）。
# 落点必须是 markdown 链接的方括号形态，避免把「已流转至 C022 相关章节」
# 这类非链接叙述误记入台账。
# 方括号后必须容许一个 (url) 段：本仓库落点全是 `[C002](../change/C002-x.md)`
# 这种带链接的写法，而 url 自身也含 `/`。若不容纳 url 段，复合记录只会匹配到
# 第一个落点，第二个源事项随之错配（实测 EN-0003 被错配到 C002）。
# 分隔符只认 `/` 与 `、`：实测多条记录之间用`；`分隔，若把`，`也算进去，
# 就有把两条独立记录并成一条复合记录的风险。
TODO_TRANSFER_RE = re.compile(
    r"((?:BG|EN|FT|TD|C)-?[0-9]{3,4}"
    r"(?:[ ]*[/、][ ]*(?:BG|EN|FT|TD|C)-?[0-9]{3,4})*)"
    r"[ ]*已流转至[ ]*"
    r"(\[C[0-9]{3}\](?:\([^)]*\))?"
    r"(?:[ ]*[/、][ ]*\[C[0-9]{3}\](?:\([^)]*\))?)*)"
)
TODO_LIST_SPLIT_RE = re.compile(r"[ ]*[/、][ ]*")

# 从「已流转至」的落点组里抽取 C 编号：只认方括号内的形态。
# markdown 链接是 `[C002](../change/C002-x.md)`，方括号后紧跟 `(url)`，
# 而 url 自身也含 `/`——若按 `/` 切片就会把复合落点切碎，只认到第一个，
# 后面的源事项会被错配或漏记。用这个正则把 url 段整体跳过。
TODO_LINK_LABEL_RE = re.compile(r"\[(C[0-9]{3})\]")
# 「拟流转目标」列在 todo 两份文档里的列名不同：now.md 叫「拟流转目标」，
# future.md 叫「拟落地方向」。按列名定位而不是硬编码列序；两个名字都要认，
# 否则 future.md 永远落在兜底列序上，列序一变就静默采错列。
TARGET_COLUMN_NAMES = ("拟流转目标", "拟落地方向")

# 「拟流转目标」列的受控枚举（docs/devel/todo/README.md）：
#   change (BugFix/Rollback/Refactor/Param) ｜ design ｜ plan/task ｜ report/test
# 实测存在「design 02 §6.1 讨论稿 → change」这类自由变体，故按**前缀**分类而非相等匹配；
# 该列是 todo 事项打算落入哪条流的唯一机器可读键，零沉淀判定离不开它。
TARGET_KIND_RULES = (
    ("change", "change"),
    ("design", "design"),
    ("plan/task", "plan_task"),
    ("plan", "plan_task"),
    ("task", "plan_task"),
    ("report", "report_test"),
    ("test", "report_test"),
)


def classify_target(target: str) -> str:
    """把「拟流转目标」列原文归入受控枚举类别（前缀匹配，大小写不敏感）。"""
    text = (target or "").strip().lower()
    for prefix, kind in TARGET_KIND_RULES:
        if text.startswith(prefix):
            return kind
    return "other"


def gather_todo(repo: Path) -> dict:
    """采集 todo/now.md 与 future.md 的待办行，以及「已流转至」账本。

    每行除 id/desc 外还采集 `target`（拟流转目标列原文）与 `target_kind`
    （按受控枚举前缀分类）——这是事项打算落入 change/ 还是 design/ 的唯一
    机器可读键；`transferred` 则是文档纪律段解析出的账本，形如
    {"EN-0010": "C022"}，是「事项已落入 change/」的权威记录。
    二者合起来才能判定「应删未删」，只凭截断的描述文本做不到。
    """
    out = {"now": [], "future": [], "transferred": {}}
    for name in ("now.md", "future.md"):
        path = repo / "docs/devel/todo" / name
        rows = []
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for m in TODO_TRANSFER_RE.finditer(text):
                # 一条记录可带多个源事项与多个落点（EN-0002/EN-0003 已流转至
                # [C002]/[C003]），两侧都按分隔符切片后按位配对。
                sources = [s for s in TODO_LIST_SPLIT_RE.split(m.group(1)) if s]
                # 落点组里夹着 markdown 链接的 (url) 段，而 url 自身也含 `/`，
                # 按分隔符整体切片会把 `[C002](../change/C002-x.md)/[C003](...)`
                # 切碎、只认到第一个落点（实测 EN-0003 因此错配到 C002）。
                # 改为只抽取方括号内的 C 编号，url 段整体跳过。
                targets = TODO_LINK_LABEL_RE.findall(m.group(2))
                if not targets:
                    continue
                # 个数不齐时给多余源事项挂上最后一个落点：宁可多记一条让人工多核，
                # 不可漏记——漏记会让应删未删的残留行从 sediment_violations 里
                # 静默消失，等于绕过红线 7 门禁。
                while len(sources) > len(targets):
                    targets.append(targets[-1])
                for source, target in zip(sources, targets):
                    out["transferred"][source] = target
            target_idx = 5  # 兜底：实测表为 7 列，目标列在第 6 列
            for line in text.splitlines():
                s = line.strip()
                if not s.startswith("|"):
                    continue
                # 跳过分隔行 |---|---|
                if re.match(r"^\|[\s:\-|]+\|$", s):
                    continue
                cells = [c.strip() for c in s.strip("|").split("|")]
                if not cells:
                    continue
                # 表头行：按列名定位目标列，不依赖硬编码列序。
                # now.md 用「拟流转目标」、future.md 用「拟落地方向」——
                # 两份文档列名不同，只认一个词会让 future.md 永远走兜底列序，
                # 哪天列序一变就静默采错列。
                if "ID" in cells:
                    for col in TARGET_COLUMN_NAMES:
                        if col in cells:
                            target_idx = cells.index(col)
                            break
                    continue
                first = cells[0]
                # 仅采集待办 ID 行，过滤表头、占位行与 Phase 路线图等其它表格
                if not TODO_ID_RE.match(first):
                    continue
                desc = cells[2] if len(cells) > 2 else (cells[1] if len(cells) > 1 else "")
                target = cells[target_idx] if len(cells) > target_idx else ""
                rows.append({
                    "id": first,
                    "desc": trunc(desc, 140),
                    "target": trunc(target, 80),
                    "target_kind": classify_target(target),
                })
        out[name.replace(".md", "")] = rows
    return out


def gather_design_docs(repo: Path) -> list:
    """采集 design/ 文档的头部元数据 + 正文原位回链标签中的 C 编号。

    `linked_changes` 来自头部『关联变更』字段，`inplace_backlinks` 来自正文的
    `> 📌 **关联变更**: [C00x]` 标签。二者在 §3.3 中是两个**独立**的同步点，
    必须分开采集——只采头部的话，「原位标签漏增」这类闭环断裂将无法被发现，
    而那时的唯一证据只是变更卡的自述。

    刻意跳过 README.md / template.md：它们是目录导览与模板，不是设计文档，
    采进来只会得到 version/status/linked_changes 全为 None 的空记录，
    既稀释 design_docs 的信噪比，也让「关联文档是否出现在 design_docs 中」
    这条核对失去意义。
    """
    docs = []
    design_dir = repo / "docs/devel/design"
    if not design_dir.is_dir():
        return docs
    for path in sorted(design_dir.glob("*.md")):
        if path.name.lower() in ("readme.md", "template.md"):
            continue
        text = path.read_text(encoding="utf-8")
        fields = parse_header_fields(text)
        backlinks = set()
        for line in text.splitlines():
            if "📌" not in line:
                continue
            for m in re.finditer(r"\bC(\d{3})\b", line):
                backlinks.add("C" + m.group(1))
        docs.append({
            "file": path.name,
            "version": fields.get("版本"),
            "status": fields.get("状态"),
            "linked_changes": fields.get("关联变更"),
            "inplace_backlinks": sorted(backlinks),
        })
    return docs


def gather_git(repo: Path) -> dict:
    """采集最近一次提交与封存目录脏标记，用于佐证回写闭环是否真的落盘。

    刻意不采集「未提交文件数」：AGENTS.md 的治理红线并未定义「工作区必须干净」，
    且该指标是瞬态值——提交前后几分钟内就会跳变，与治理质量无关，只会无谓
    拉低 Jev 的判定置信度。只保留有流程依据的信号：
      · last_commit —— 回写是否落盘的佐证；
      · frozen_dir_dirty —— 红线 2「docs/devel/task 与 docs/devel/plan 已随
        Phase 1 封存，一律不修改」的可判定信号。

    git 输出显式指定 utf-8 + errors=replace：否则在 ASCII/POSIX locale 的 CI 上，
    非 ASCII 提交信息会触发 UnicodeDecodeError 被 except 吞成空串，或解出乱码。
    """
    def run(args):
        try:
            return subprocess.run(args, cwd=repo, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=15).stdout
        except Exception:
            return ""

    frozen_raw = run(["git", "status", "--porcelain", "--",
                      "docs/devel/plan", "docs/devel/task"])
    # 未跟踪新增（??）不算违规：Phase 2 立项允许在 plan/task 新建卡片，
    # 那是规则明确允许的动作；只有已跟踪文件被改/删/改名才是红线 2 要拦的。
    frozen_dirty = any(
        line[:2] != "??" for line in frozen_raw.splitlines() if line.strip()
    )
    return {
        "last_commit": run(["git", "log", "-1", "--format=%h %s"]).strip(),
        "frozen_dir_dirty": frozen_dirty,
    }


def build_state(repo: Path) -> dict:
    cards = gather_change_cards(repo)
    todo = gather_todo(repo)  # 只采集一次：now/future/账本同源，避免重复读盘
    git = gather_git(repo)
    return {
        "governance_process": GOVERNANCE_PROCESS,
        "current_state": {
            "change_cards": cards,
            # 代码侧硬判块：Jev 的采信依据，也是红线 7 违规门禁的第一道闸
            "code_assertions": build_code_assertions(cards, todo, git["frozen_dir_dirty"]),
            "latest_verified_card": latest_verified_card(repo, cards),
            "todo_now": todo["now"],
            "todo_future": todo["future"],
            "todo_transferred": todo["transferred"],
            "changelog": gather_changelog(repo),
            "design_docs": gather_design_docs(repo),
            "git": git,
        },
    }


def _tally(cards: list) -> dict:
    tally: dict = {}
    for c in cards:
        key = c.get("status") or "(缺失)"
        tally[key] = tally.get(key, 0) + 1
    return tally

def build_code_assertions(cards: list, todo: dict, frozen_dir_dirty: bool = False) -> dict:
    """代码侧硬判块：把 AGENTS.md 中可确定性比对的规则算成事实，供 Jev 直接采信。

    刻意只做「有明确枚举或账本可依」的判定，不发明判据：
      · illegal_status / illegal_type —— 对照 GOVERNANCE_PROCESS 的受控枚举做**严格相等**。
        红线 5 要求状态枚举纯净，严格相等可同时抓住「核验通过（x）」这类括号小尾巴；
      · pending_cards —— 状态为 待核验 的卡（代码查表即可判，不必问模型）；
      · unmerged_cards —— 已 核验通过 但卡正文「关联提交」取不到 commit hash，
        即尚未合入主干。这是区分 awaiting_merge_or_release 与 idle 的唯一可靠判别器：
        CHANGELOG 日期是版本冻结日而非条目写入日，拿日期比较会把「已登记未打 tag」
        误判成正常维护空闲态。判据刻意用「是否为 hash」而非字面量「待提交」——
        后者在出现裸 hash、或 `abc1234 (squash)` 这类变体写法时会把已合入的卡
        误判成待合入（方向虽严，但会把 idle 态永久卡在合入等待）；
      · sediment_violations —— 仍留在 todo 表内、但其 ID 已登记进「已流转至」账本的事项，
        即零沉淀纪律被破坏的确定性证据；
      · frozen_dir_dirty —— 红线 2 的封存目录（docs/devel/plan、docs/devel/task）
        中**已跟踪**文件被改动。

    注意 pending_cards / unmerged_cards / frozen_dir_dirty 里，前两者只是**阶段判别器**
    而非违规（等待核验、等待合入都是治理流的正常中间态），是否算违规由
    cross_check() 与 detect_violation() 决定；frozen_dir_dirty 则是红线 2 的直接违反。
    """
    status_enum = set(GOVERNANCE_PROCESS["change_card_status_enum"])
    type_enum = set(GOVERNANCE_PROCESS["change_card_type_enum"])
    transferred = todo.get("transferred", {})
    rows = list(todo.get("now", [])) + list(todo.get("future", []))
    return {
        "illegal_status": sorted({c["id"] for c in cards if c.get("status") not in status_enum}),
        "illegal_type": sorted({c["id"] for c in cards if c.get("type") not in type_enum}),
        "pending_cards": sorted(c["id"] for c in cards if c.get("status") == "待核验"),
        "unmerged_cards": sorted(
            c["id"] for c in cards
            if c.get("status") == "核验通过" and not _is_commit_hash(c.get("linked_commit"))
        ),
        "sediment_violations": sorted(
            {row["id"] for row in rows if row["id"] in transferred}
        ),
        "frozen_dir_dirty": bool(frozen_dir_dirty),
    }


# ---------------------------------------------------------------------------
# 调用 Jev
# ---------------------------------------------------------------------------

def _build_ssl_context() -> ssl.SSLContext:
    """构造一个"仍然校验证书"的 HTTPS 上下文。

    部分 Python 安装（如 python.org 框架版）默认没有挂载任何 CA bundle，
    直接 urlopen 会抛 CERTIFICATE_VERIFY_FAILED。这里按优先级挑一个真实
    存在的 CA bundle：SSL_CERT_FILE 环境变量 -> certifi -> 系统
    /etc/ssl/cert.pem -> OpenSSL 默认路径；都拿不到才退回系统默认上下文。
    全程不关闭证书校验（verify_mode 保持 VERIFY_REQUIRED）。
    """
    candidates = []
    env_ca = os.environ.get("SSL_CERT_FILE")
    if env_ca:
        candidates.append(env_ca)
    try:
        import certifi  # type: ignore

        candidates.append(certifi.where())
    except Exception:
        pass
    candidates.append("/etc/ssl/cert.pem")
    for ca in candidates:
        if not ca:
            continue
        try:
            p = Path(ca)
            if p.is_file():
                return ssl.create_default_context(cafile=ca)
            if p.is_dir():
                return ssl.create_default_context(capath=ca)
        except Exception:
            continue
    return ssl.create_default_context()


def call_jev(state: dict, api_key: str, model: str) -> dict:
    payload = json.dumps(
        {"state": state, "model": model, "questions": QUESTIONS},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        TYPESAFE_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT,
                                    context=_build_ssl_context()) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # exc.read() 自身也可能抛（连接已被对端断开），故整段兜住
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            body = "（响应体读取失败）"
        hint = {
            401: "API Key 无效或未授权（检查 TYPESAFE_API_KEY）",
            403: "无权访问（检查 Key 权限）",
            429: "触发限流，请稍后重试",
        }.get(exc.code)
        # 状态码必须出现在消息里：运维按码定位，hint 只是人话解释
        detail = f"HTTP {exc.code}" + (f"：{hint}" if hint else "")
        raise RuntimeError(f"TypeSafe API 报错：{detail}\n响应体：{trunc(body, 500)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 TypeSafe API（{TYPESAFE_ENDPOINT}）：{exc}") from exc
    except (TimeoutError, OSError) as exc:
        # 读超时（socket.timeout，3.10 起即 TimeoutError）不是 URLError 的子类，
        # 会从上面两个分支漏出去炸成 exit 1；ssl.SSLError 等 OSError 同样收口于此。
        raise RuntimeError(f"连接或读取 TypeSafe API 失败：{exc!r}") from exc
    except Exception as exc:  # 其余一律收敛为 exit 3，不留裸崩的 exit 1
        raise RuntimeError(f"调用 TypeSafe API 出现意外错误：{exc!r}") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        # 非 JSON 响应（HTML 错误页、空体、被截断的半包）不能静默当成通过
        raise RuntimeError(f"TypeSafe API 返回了非 JSON 响应：{trunc(raw, 500)}") from exc


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def print_facts(state: dict) -> None:
    """打印代码侧采集事实。

    与 Jev 语义判定并排展示，供人工交叉校验：`code_assertions` 是确定性结论，
    Jev 的 Noul/Choice 只是语义解读，两者不一致时以代码硬判为准。
    """
    cs = state["current_state"]
    cards = cs["change_cards"]
    tally = _tally(cards)
    tally_str = "、".join(f"{k}×{v}" for k, v in tally.items()) or "无"
    print("── 采集事实（代码确定性采集）────────────────────────────")
    print(f"  变更卡总数：{len(cards)}    状态分布：{tally_str}")
    lvc = cs["latest_verified_card"]
    if lvc:
        print(f"  最新已核验通过卡：{lvc['id']}（{lvc.get('type')}，{lvc.get('created')}，"
              f"关联提交 {lvc.get('linked_commit') or '未填'}）")
    else:
        print("  最新已核验通过卡：无")
    ca = cs["code_assertions"]
    print(f"  代码硬判：非法状态 {ca['illegal_status'] or '无'}｜非法类型 {ca['illegal_type'] or '无'}｜"
          f"待核验 {ca['pending_cards'] or '无'}｜已核验未合入 {ca['unmerged_cards'] or '无'}｜"
          f"应删未删 {ca['sediment_violations'] or '无'}")
    if ca.get("frozen_dir_dirty"):
        print("  代码硬判：docs/devel/plan 或 docs/devel/task 存在已跟踪文件被改动"
              "（红线 2：任务卡/计划卡已封存只读）")
    cl = cs["changelog"]
    if cl:
        print(f"  CHANGELOG 顶部版本：[{cl.get('version')}] - {cl.get('date')}")

    def _rows(key: str) -> list:
        return [f"{r['id']}({r['target_kind']})" for r in cs[key]] or ["无"]

    print(f"  todo/now 残留事项：{_rows('todo_now')}")
    print(f"  todo/future 残留事项：{_rows('todo_future')}")
    transferred = cs["todo_transferred"]
    tail = f"，最近 {list(transferred.items())[-3:]}" if transferred else ""
    print(f"  todo 流转账本：{len(transferred)} 条{tail}")
    if lvc:
        target = lvc["id"]
        linked = lvc.get("linked_design") or ""
        for d in cs["design_docs"]:
            if linked and d["file"] in linked:
                in_head = target in (d.get("linked_changes") or "")
                in_body = target in (d.get("inplace_backlinks") or [])
                print(f"  design 同步证据 [{d['file']}]：头部关联变更 {'✓' if in_head else '✗'}｜"
                      f"正文原位标签 {'✓' if in_body else '✗'}｜版本 {d.get('version')}")
    git = cs["git"]
    print(f"  最近提交：{git['last_commit'] or '无'}")
    print("")


def _fmt_conf(v) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def print_jev_answers(resp: dict) -> None:
    answers = resp.get("answers", {})
    model = resp.get("model", "?")
    usage = resp.get("usage", {})
    print("── Jev 语义判定 ────────────────────────────────────────")
    print(f"  模型：{model}    token 用量：in={usage.get('input_tokens', '?')} "
          f"out={usage.get('output_tokens', '?')}")

    # Choice: 当前阶段
    stage = answers.get("current_stage", {})
    choice = stage.get("choice")
    conf = stage.get("confidence")
    label = STAGE_LABELS.get(choice, choice)
    flag = "" if (conf is not None and conf >= CONFIDENCE_GATE) else "  ⚠ 低置信，建议人工复核"
    print(f"  · 当前阶段 (Choice)：{label}  [置信 {_fmt_conf(conf)}]{flag}")
    probs = stage.get("probabilities", {})
    if probs:
        ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
        dist = "，".join(f"{STAGE_LABELS.get(k, k)} {v:.2f}" for k, v in ranked if v > 0.01)
        if dist:
            print(f"      分布：{dist}")

    # Noul 三连：同时展示概率与置信。低置信一律标注，避免把弱判断印成确定结论
    # （代码侧已采信 code_assertions，这里只是语义解读，两者不一致时以代码硬判为准）。
    # 题目清单与标签取 NOUL_QIDS / NOUL_LABELS 单一数据源：新增一道 Noul 题时
    # 只需改 QUESTIONS 与这两个常量，展示层不会漏题、标签不会漂移。
    for qid in NOUL_QIDS:
        cn = NOUL_LABELS[qid]
        ans = answers.get(qid, {})
        p = ans.get("noul")
        if not _is_num(p):
            print(f"  · {cn} (Noul)：（无有效概率值）")
            continue
        conf = ans.get("confidence")
        if abs(p - 0.5) < NOUL_UNCERTAIN_BAND:
            verdict = "不确定（概率落入不确定带）"
        else:
            verdict = "是" if p >= 0.5 else "否"
        # noul 题的响应不带 confidence 字段（实测），概率是它唯一的信号。
        # 因此不再对 None 打「低置信」——那会让每一行都常驻 ⚠ 噪音、把提示稀释成
        # 背景音；只有真的带回低置信值时才提示人工复核。
        if conf is None:
            flag = "  （noul 型无置信字段，以概率为准）"
        elif conf < CONFIDENCE_GATE:
            flag = "  ⚠ 低置信，建议人工复核"
        else:
            flag = ""
        print(f"  · {cn} (Noul)：{verdict}  [P(yes)={p:.2f} 置信 {_fmt_conf(conf)}]{flag}")

    # Choice: 整体合规档位。刻意不用 Score 型——实测 Jev 在 Score 型下会按
    # 1~5 里克特刻度给分（三次实跑 2.40/2.43/2.48），与声明的 [0,1] 对不上，
    # 越界回填会把「中等」误显示成「完全符合治理流程」。改由模型直接选档位、
    # 代码按 COMPLIANCE_BANDS 映射代表值，刻度歧义随之消失。
    comp = answers.get("compliance", {})
    choice = comp.get("choice")
    if choice in COMPLIANCE_BAND_OF:
        conf = comp.get("confidence")
        flag = "" if (conf is not None and conf >= CONFIDENCE_GATE) else "  ⚠ 低置信，建议人工复核"
        print(f"  · 整体合规 (Choice)：{choice}"
              f"（代表值 {COMPLIANCE_BAND_OF[choice]:.2f}）  [置信 {_fmt_conf(conf)}]{flag}")
        probs = comp.get("probabilities", {})
        if probs:
            ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
            dist = "，".join(f"{k} {v:.2f}" for k, v in ranked if v > 0.01)
            if dist:
                print(f"      分布：{dist}")
    print("")


def expected_stage(ca: dict) -> str:
    """按治理流的自然次序算出代码侧**唯一**期望的阶段标签。

    阶段是单一标签，因此不能对每条事实各设一条约束：待核验卡与已核验未合入卡
    在本仓库是并存的常态（每开一张新 C 卡，上一张往往还没合入），两条独立约束
    会互相制造矛盾、把正常中间态误拦成 exit 4。改为取「最早未完成的步骤」：
      任一违规事实（非法枚举 / 应删未删 / 封存目录被改）→ has_violation
      有待核验卡                                    → awaiting_verification
      有已核验未合入卡                              → awaiting_merge_or_release
      其余                                          → idle
    """
    if (ca["illegal_status"] or ca["illegal_type"] or ca["sediment_violations"]
            or ca.get("frozen_dir_dirty")):
        return "has_violation"
    if ca["pending_cards"]:
        return "awaiting_verification"
    if ca["unmerged_cards"]:
        return "awaiting_merge_or_release"
    return "idle"


def _stage_facts(ca: dict) -> str:
    """把驱动阶段判别的代码事实拼成一句可读描述，供矛盾提示定位。"""
    facts = []
    if ca["illegal_status"]:
        facts.append(f"状态非法 {ca['illegal_status']}")
    if ca["illegal_type"]:
        facts.append(f"类型非法 {ca['illegal_type']}")
    if ca["sediment_violations"]:
        facts.append(f"应删未删 {ca['sediment_violations']}")
    if ca.get("frozen_dir_dirty"):
        facts.append("封存目录被改动")
    if ca["pending_cards"]:
        facts.append(f"待核验 {ca['pending_cards']}")
    if ca["unmerged_cards"]:
        facts.append(f"已核验未合入 {ca['unmerged_cards']}")
    return "；".join(facts) or "无未完成步骤"


def cross_check(resp: dict, state: dict) -> list:
    """阶段判别器与代码事实的一致性校验（红线 7 门禁的第二道闸）。

    `code_assertions` 里的 pending_cards / unmerged_cards 是**阶段判别器**而不是
    违规本身：有待验卡只说明流停在「等待核验」，已验未合入只说明停在「等待合入」。
    但 Jev 若把这两类状态判成「空闲」或「已同步」，就是语义判定与代码事实矛盾。
    此时按红线 7「违规即阻断」从严：宁可误拦（人工核事实后可放行），不可静默放行
    ——静默放行正是红线 7 要防的风险。

    校验方式是拿 `expected_stage()` 算出的唯一期望标签比对立项，而不是对每条
    事实各设一条允许集——后者在「待核验 + 已核验未合入」并存时会自相矛盾
    （详见 expected_stage 注释）。

    放行集 = {expected, has_violation, awaiting_bidirectional_sync}。后两者属
    「代码侧无法否证」：模型判出代码侧没发现的违规时不得反被本校验拦（方向从
    严）；同步是否闭环同样是语义判断，代码侧两个方向都裁不了，故无条件放行，
    不随 unmerged_cards 是否为空而收紧。其余三个标签仍由 pending_cards /
    unmerged_cards 约束。

    sediment_violations 与非法枚举两类不在此重复：代码侧已在 detect_violation
    直接产出理由。resp 为空（--offline）或缺 current_stage 时无从交叉校验，
    直接返回空列表，交由代码侧理由兜底。
    """
    answers = resp.get("answers", {})
    stage = answers.get("current_stage", {}).get("choice")
    if stage is None:
        return []
    ca = state["current_state"]["code_assertions"]
    expected = expected_stage(ca)
    # awaiting_bidirectional_sync 与 has_violation 同属「代码侧无法否证」的标签：
    # 同步是否闭环是语义判断（design 原位回链 / 头部关联变更 / CHANGELOG 互链都要
    # 读正文才能确认），代码侧两个方向都裁不了，故无条件放行。
    # 曾经的写法是仅当 unmerged_cards 非空才放行——那会造成反向漏洞：所有卡都已
    # 合入（expected 退化为 idle）时它反而不被放行，Jev 一旦对同步闭环猜疑就被升级
    # 成 exit 4 硬违规。而 unmerged_cards 为空正是每次正常收口后的必经路径，等于每个
    # 干净检查点都会被误拦一次——干净检查点被拦会训练运营者忽略退出码，这比漏拦更
    # 危险。真实未闭环仍由 sync_complete noul 门禁与 compliance 档位闸独立兜住，
    # 不依赖本放行集。
    allowed = {expected, "has_violation", "awaiting_bidirectional_sync"}
    if stage in allowed:
        return []
    return [
        f"阶段判定与代码事实矛盾：{_stage_facts(ca)}，"
        f"代码侧期望「{STAGE_LABELS.get(expected, expected)}」，"
        f"实际判为「{STAGE_LABELS.get(stage, stage)}」"
    ]


def _choice_confidence(answers: dict, qid: str):
    """取 Choice 题答案的置信度；答案缺失或置信非数值时返回 None。

    noul 题的响应不带 confidence 字段（实测），因此本函数只用于 Choice 题。
    """
    ans = answers.get(qid)
    if not isinstance(ans, dict):
        return None
    conf = ans.get("confidence")
    return conf if _is_num(conf) else None


def _conf_gate_pass(answers: dict, qid: str) -> bool:
    """Choice 题置信是否达到门控阈值；无置信字段或缺失时返回 False。"""
    conf = _choice_confidence(answers, qid)
    return conf is not None and conf >= CONFIDENCE_GATE


def semantic_review_items(resp: dict) -> list:
    """列出置信低于 CONFIDENCE_GATE 的 Choice 型语义判定，供人工复核。

    只覆盖两道 Choice 题（current_stage / compliance）：noul 题没有 confidence
    字段，概率本身就是它的全部信号，不由本函数判定。

    低置信判定**不**作为硬判据：AGENTS.md 规定「任一判定置信低于 0.60 … 结论
    仅供参考，须人工核对采集事实后决策」。它既不是「存在治理违规」的确定结论
    （不能走 exit 4），也不构成自检通过，故由 main() 收敛为 exit 6，逼一次人工
    复核。实证依据：重叠卡态（新卡待核验 + 上一张已核验未合入）下合规档位分布
    接近平手（0.44 vs 0.42）、置信 0.30~0.52，此时硬拦会误伤正常中间态，
    静默放行又会绕过红线 7——转人工正是规则给的正解。
    """
    answers = resp.get("answers", {})
    items = []
    for qid, label in (("current_stage", "当前阶段"), ("compliance", "整体合规")):
        conf = _choice_confidence(answers, qid)
        if conf is None or conf >= CONFIDENCE_GATE:
            continue
        choice = answers[qid].get("choice")
        shown = STAGE_LABELS.get(choice, choice) if qid == "current_stage" else choice
        items.append(f"{label}「{shown}」置信 {conf:.2f}")
    # noul 题没有 confidence 字段，其"不确定"由概率落入 NOUL_UNCERTAIN_BAND 表达
    for qid, label in NOUL_LABELS.items():
        p = answers.get(qid, {}).get("noul")
        if _is_num(p) and abs(p - 0.5) < NOUL_UNCERTAIN_BAND:
            items.append(f"{label}「概率落入不确定带」P={p:.2f}")
    return items


def detect_violation(resp: dict, state: dict) -> list:
    """汇总违规证据：代码侧硬校验 + Jev 语义判定 + 交叉校验，任一命中即违规。

    置信门控只作用于 Choice 型语义判定（compliance 档位、current_stage 判为
    has_violation、以及由 current_stage 派生的 cross_check）：置信未达
    CONFIDENCE_GATE 时这些判定降级为 semantic_review_items 的人工复核项，
    不在此硬拦。noul 题没有 confidence 字段，其违规门禁只看概率：概率明确越界才
    拦，落入 NOUL_UNCERTAIN_BAND 的"不确定"转 semantic_review_items 交人工复核；
    代码侧硬判与 Jev 无关，任何模式下都同权执行。
    """
    reasons = []
    ca = state["current_state"]["code_assertions"]
    if ca["illegal_status"]:
        reasons.append(f"状态值非法：{ca['illegal_status']}")
    if ca["illegal_type"]:
        reasons.append(f"类型值非法：{ca['illegal_type']}")
    if ca["sediment_violations"]:
        reasons.append(f"todo 应删未删：{ca['sediment_violations']}")
    if ca.get("frozen_dir_dirty"):
        reasons.append("docs/devel/plan 或 docs/devel/task 的已封存卡片被改动（红线 2）")
    answers = resp.get("answers", {})
    # Noul 违规门禁：按 NOUL_POLARITY 声明的极性判侧，措辞同源，不与展示层漂移
    for qid, (side, phrase) in NOUL_POLARITY.items():
        p = answers.get(qid, {}).get("noul")
        if not _is_num(p):
            continue
        # 概率落入不确定带时既非"是"也非"否"：展示层据此标「不确定」，门禁层
        # 就不能反过来给确定性结论。交 semantic_review_items 转人工复核（exit 6），
        # 否则会出现答案行写「不确定」、结论行写「仍有同步点缺失」的自相矛盾。
        if abs(p - 0.5) < NOUL_UNCERTAIN_BAND:
            continue
        crossed = p < 0.5 if side == "low" else p >= 0.5
        if crossed:
            reasons.append(f"{phrase}（P={p:.2f}）")
    # 以下三项都是 Choice 型语义判定，须过置信门控
    if _conf_gate_pass(answers, "compliance"):
        band = compliance_band_value(answers.get("compliance", {}).get("choice"))
        if band is not None and band < COMPLIANCE_VIOLATION_BELOW:
            reasons.append(f"合规档位「{answers['compliance']['choice']}」低于阈值 "
                           f"{COMPLIANCE_VIOLATION_BELOW:g}（代表值 {band:.2f}）")
    if _conf_gate_pass(answers, "current_stage"):
        if answers.get("current_stage", {}).get("choice") == "has_violation":
            reasons.append("阶段判定为存在治理违规")
        reasons.extend(cross_check(resp, state))
    return reasons


def print_recommendation(resp: dict, reasons: list, review: list = None) -> None:
    print("── 建议下一步 ──────────────────────────────────────────")
    # 低置信项无条件先印：它可能与违规同时出现，先让人看到「哪些判定本身就不牢」，
    # 避免只看见结论、看不见结论的置信度。
    for item in (review or []):
        print(f"  ⚠ 低置信判定（仅供参考，未用作硬判据）：{item}")
    if reasons:
        print("  检测到治理违规：" + "；".join(reasons))
        print("  按 AGENTS.md 红线 7『违规即阻断』：存在治理违规不得合入主干，"
              "请先按上方事实定位修复，再重跑本自检。")
        print("")
        return
    if review:
        print(f"  未发现确定性违规，但有 {len(review)} 项语义判定置信低于 "
              f"{CONFIDENCE_GATE:g}。按 AGENTS.md『低置信需人工复核』：结论仅供参考，"
              "请人工核对上方采集事实后决策；")
        print("  人工确认前，本次自检不得视为已完成（退出码 6）。")
        print("")
        return
    answers = resp.get("answers", {})
    stage = answers.get("current_stage", {}).get("choice")
    if stage is None:
        # --offline 走到这里：没有 Jev 语义判定，拿空 stage 查 tips 表只会得到
        # 「无明确建议」。必须讲清「只过了代码侧硬判，语义判定还没做」。
        print("  代码侧硬判未发现违规。注意：--offline 只做确定性采集与代码硬判，"
              "双向同步 / 零沉淀等语义判定被跳过——收口前请联网重跑本脚本完成自检。")
        print("")
        return
    tips = {
        "awaiting_verification": "有卡待核验：跑测试命令并在会话向人工汇报事实，人工确认后由 AI 代签收口。",
        "awaiting_bidirectional_sync": "已核验通过但同步未闭环：补齐 design 原位回链 / 头部关联变更 / CHANGELOG 互链 / 版本号。",
        "awaiting_merge_or_release": "已核验通过且已同步：可合入主干，纳入版本时打 vX.Y.Z tag。",
        "has_violation": "检测到治理违规：按上文 Noul/Choice 定位违规点，优先修复后再合入。",
        "idle": "无进行中变更：治理流处于干净检查点。",
    }
    print(f"  {tips.get(stage, '（无明确建议）')}")
    print("")


def validate_response(resp: dict):
    """校验 Jev 响应结构；返回问题描述或 None。

    门禁语义（AGENTS.md 红线 7「违规即阻断」）：响应缺 answers、缺任一大题、
    或关键字段非数值，一律判为「自检未完成」（exit 5），绝不把残缺响应当成通过。

    除 choice/noul 外还必须校验 `confidence` 与 `probabilities` 的**类型**：
    `print_jev_answers` 会对它们做数值运算（`f"{v:.2f}"`、`sorted(probs.items())`），
    畸形形状若在此放过，就会留到打印阶段崩成 exit 1——那比判为无效更糟。
    """
    if not isinstance(resp, dict):
        return "响应不是 JSON 对象"
    answers = resp.get("answers")
    if not isinstance(answers, dict) or not answers:
        return "响应缺少 answers"
    missing = [qid for qid in QUESTIONS if qid not in answers]
    if missing:
        return f"响应缺少题目答案：{missing}"
    stage = answers.get("current_stage")
    if not isinstance(stage, dict) or stage.get("choice") not in STAGE_LABELS:
        return (f"current_stage.choice 缺失或不在受控阶段内"
                f"（应为 {list(STAGE_LABELS)} 之一）")
    for qid in NOUL_QIDS:
        ans = answers.get(qid)
        if not isinstance(ans, dict) or not _is_num(ans.get("noul")):
            return f"{qid}.noul 缺失或非数值"
    comp = answers.get("compliance")
    choice = comp.get("choice") if isinstance(comp, dict) else None
    if choice not in COMPLIANCE_BAND_OF:
        return (f"compliance.choice 缺失或不在受控档位内"
                f"（应为 {list(COMPLIANCE_BAND_OF)} 之一）")
    for qid in QUESTIONS:
        ans = answers.get(qid)
        if not isinstance(ans, dict):
            continue
        conf = ans.get("confidence")
        if conf is not None and not _is_num(conf):
            return f"{qid}.confidence 非数值（实际为 {type(conf).__name__}）"
        probs = ans.get("probabilities")
        if probs is None:
            continue
        if not isinstance(probs, dict) or not all(_is_num(v) for v in probs.values()):
            return f"{qid}.probabilities 非「选项 → 数值」字典"
    return None


# ---------------------------------------------------------------------------

def load_api_key_from_credentials() -> "str | None":
    """从凭据文件读取 TYPESAFE_API_KEY；环境变量优先，已设置则不覆盖。

    查找顺序：$TYPESAFE_CREDENTIALS_FILE -> ~/.config/typesafe/credentials.env。
    只解析 KEY=VALUE 行，忽略注释与空行，剥离首尾引号。取到的值仅用于请求
    Authorization 头，任何输出路径都不打印它。
    """
    candidates = []
    override = os.environ.get("TYPESAFE_CREDENTIALS_FILE")
    if override:
        candidates.append(Path(override))
    candidates.append(Path.home() / ".config" / "typesafe" / "credentials.env")
    for path in candidates:
        try:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                # .env 通行写法带 export 前缀，先剥掉再取键名，否则会误判为「未检测到 key」
                line = re.sub(r"^export\s+", "", line)
                key, value = line.split("=", 1)
                if key.strip() != "TYPESAFE_API_KEY":
                    continue
                value = value.strip().strip('"').strip("'")
                if value:
                    return value
        except Exception:
            continue
    return None

# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="用 TypeSafe Jev 检查 QTVictory 文档治理工作流状态。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--offline", action="store_true",
                        help="只采集并打印状态事实，不调用 Jev。")
    parser.add_argument("--json", action="store_true",
                        help="打印将发给 Jev 的请求体（state+questions）后退出，不调用 API。")
    parser.add_argument("--api-key", default=None,
                        help="TypeSafe API Key（默认读环境变量 TYPESAFE_API_KEY，"
                             "其次读 ~/.config/typesafe/credentials.env）。"
                             "⚠ 命令行传 key 会出现在 ps 等进程列表中，"
                             "优先使用环境变量或凭据文件。")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"模型名（默认 {DEFAULT_MODEL}）。")
    args = parser.parse_args()

    repo = find_repo_root()
    state = build_state(repo)

    if args.json:
        print(json.dumps({"state": state, "model": args.model, "questions": QUESTIONS},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"仓库根：{repo}")
    print_facts(state)

    api_key = args.api_key or os.environ.get("TYPESAFE_API_KEY") or load_api_key_from_credentials()
    if args.offline:
        # 代码侧硬判（illegal_status / illegal_type / sediment_violations）与 Jev 无关，
        # 离线模式必须同权门禁：只打印不判罚等于让红线 7 在无 key 的 CI 上失效。
        # 传空 answers 即只取代码侧理由，Jev 语义判定仍照旧跳过。
        print("（--offline：已跳过 Jev 语义判定；代码侧确定性硬判门禁照常执行。）")
        reasons = detect_violation({}, state)
        print_recommendation({}, reasons)
        return 4 if reasons else 0
    if not api_key:
        sys.stderr.write(
            "未检测到 TYPESAFE_API_KEY，已跳过 Jev 语义判定（上方为采集事实）。\n"
            "  设置方式：export TYPESAFE_API_KEY=sk-...   （在 https://console.typesafe.ai/keys 创建）\n"
            "  或写入 ~/.config/typesafe/credentials.env（本脚本会自动读取该文件）；\n"
            "  或先跑 --offline / --json 查看状态与将发送的请求体。\n"
        )
        return 2

    try:
        resp = call_jev(state, api_key, args.model)
    except RuntimeError as exc:
        sys.stderr.write(f"调用 Jev 失败：{exc}\n")
        return 3

    problem = validate_response(resp)
    if problem:
        sys.stderr.write(f"Jev 响应无效，自检未完成：{problem}\n")
        return 5

    print_jev_answers(resp)
    reasons = detect_violation(resp, state)
    review = semantic_review_items(resp)
    print_recommendation(resp, reasons, review)
    if reasons:
        return 4
    if review:
        # AGENTS.md：任一判定置信低于 0.60 时「结论仅供参考，须人工核对采集
        # 事实后决策」。既不能当成违规（那是 exit 4），也不算自检通过，
        # 故单独占一个退出码，逼一次人工复核。
        return 6
    return 0


if __name__ == "__main__":
    sys.exit(main())
