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
  # 需要先把 API Key 放入环境（在 https://console.typesafe.ai/keys 创建）
  export TYPESAFE_API_KEY=sk-...
  python3 scripts/jev_workflow_check.py                 # 采集 + 调用 Jev + 解读
  python3 scripts/jev_workflow_check.py --json          # 只打印将发给 Jev 的请求体,不调用
  python3 scripts/jev_workflow_check.py --offline       # 只采集状态并打印事实,不调用 Jev
  python3 scripts/jev_workflow_check.py --api-key sk-.. # 用命令行传 key(替代环境变量)

退出码：0 正常；2 缺 key；3 采集或网络/API 失败；4 检测到治理违规（红线 7 门禁：存在违规不得合入主干）；5 Jev 响应无效（自检未完成，须修复后重跑）。
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

# 置信门控阈值：低于该值则在输出中标注"低置信，建议人工复核"。
CONFIDENCE_GATE = 0.60
# Noul 概率距 0.5 小于该值视为"不确定"。
NOUL_UNCERTAIN_BAND = 0.15

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
COMPLIANCE_LABELS = tuple(band[0] for band in COMPLIANCE_BANDS)
COMPLIANCE_BAND_OF = {band[0]: band[1] for band in COMPLIANCE_BANDS}
# 红线 7 门禁阈值：落入「存在明确违规」档即阻断合入。
COMPLIANCE_VIOLATION_BELOW = 0.40


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
            "① `has_violation`：`current_state.code_assertions` 的 `illegal_status` /"
            " `illegal_type` / `sediment_violations` 任一非空（代码硬判，直接采信）；\n"
            "② `awaiting_verification`：`code_assertions.pending_cards` 非空；\n"
            "③ `awaiting_bidirectional_sync`：存在 核验通过 的卡，但"
            " `governance_process.bidirectional_sync_points` 仍有同步点未闭环——以"
            " `latest_verified_card`、`design_docs[].inplace_backlinks`、`changelog` 为证；\n"
            "④ `awaiting_merge_or_release`：`code_assertions.unmerged_cards` 非空，"
            "即已核验通过且同步完成、但「关联提交」仍为『待提交』尚未合入主干；\n"
            "⑤ `idle`：以上皆不成立——所有卡均已核验通过、同步闭环且已合入。\n"
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
            "针对 `current_state.latest_change_card`（最新一张已 核验通过 的卡），"
            "逐项核对 `governance_process.bidirectional_sync_points` 的同步点。"
            "注意 design/ 的『原位反向引用标签』与『头部关联变更字段』是两个**独立**同步点，"
            "须分别取证：`current_state.design_docs[].inplace_backlinks` 是正文 📌 标签中"
            "提取到的 C 编号列表，`linked_changes` 是头部字段，二者不可互相替代。"
            "另需核对 `current_state.changelog` 是否已登记并互链该卡，"
            "以及该卡 `linked_design` 指向的文档是否确实出现在 `design_docs` 中。"
            "卡正文的 checklist 只是自述，不能作为同步已完成的证据。"
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


def gather_change_cards(repo: Path) -> list:
    cards = []
    change_dir = repo / "docs/devel/change"
    for path in sorted(change_dir.glob("C*.md")):
        if path.name.lower() == "template.md":
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
    """取最新一张『核验通过』的卡，附上核验清单与结论摘录，供 Jev 核对同步点。"""
    verified = [c for c in cards if c.get("status") == "核验通过"]
    if not verified:
        return None
    latest = verified[-1]
    full = (repo / latest["file"]).read_text(encoding="utf-8")
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
# 连字符取可选：现行待办 ID 为 4 位带连字符形态，另需兼容遗留的无连字符
# 形态（C001 已流转至 [C001](...)）。目标是 markdown 链接，故用方括号锚定，
# 避免把「已流转至 C022 相关章节」这类非链接叙述误记入台账。
TODO_TRANSFER_RE = re.compile(r"((?:BG|EN|FT|TD|C)-?[0-9]{3,4})[ ]*已流转至[ ]*\[(C[0-9]{3})\]")
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
                out["transferred"][m.group(1)] = m.group(2)
            target_idx = 5  # 兜底：实测表为 7 列，拟流转目标在第 6 列
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
                # 表头行：按列名定位「拟流转目标」，不依赖硬编码列序
                if "拟流转目标" in cells and "ID" in cells:
                    target_idx = cells.index("拟流转目标")
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
    必须分开采集——只采头部的话，"原位标签漏增"这类闭环断裂将无法被发现，
    而那时的唯一证据只是变更卡的自述。
    """
    docs = []
    design_dir = repo / "docs/devel/design"
    if not design_dir.is_dir():
        return docs
    for path in sorted(design_dir.glob("*.md")):
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
    """采集最近一次提交，用于佐证回写闭环是否真的落盘。

    刻意不采集"未提交文件数"：AGENTS.md 的治理红线并未定义"工作区必须干净"，
    且该指标是瞬态值——提交前后几分钟内就会跳变，与治理质量无关，只会无谓
    拉低 Jev 的判定置信度。只保留有流程依据的信号。
    """
    def run(args):
        try:
            return subprocess.run(args, cwd=repo, capture_output=True,
                                  text=True, timeout=15).stdout
        except Exception:
            return ""

    return {
        "last_commit": run(["git", "log", "-1", "--format=%h %s"]).strip(),
    }


def build_state(repo: Path) -> dict:
    cards = gather_change_cards(repo)
    todo = gather_todo(repo)  # 只采集一次：now/future/账本同源，避免重复读盘
    return {
        "governance_process": GOVERNANCE_PROCESS,
        "current_state": {
            "change_cards": cards,
            # 代码侧硬判块：Jev 的采信依据，也是红线 7 违规门禁的第一道闸
            "code_assertions": build_code_assertions(cards, todo),
            "latest_verified_card": latest_verified_card(repo, cards),
            "todo_now": todo["now"],
            "todo_future": todo["future"],
            "todo_transferred": todo["transferred"],
            "changelog": gather_changelog(repo),
            "design_docs": gather_design_docs(repo),
            "git": gather_git(repo),
        },
    }


def _tally(cards: list) -> dict:
    tally: dict = {}
    for c in cards:
        key = c.get("status") or "(缺失)"
        tally[key] = tally.get(key, 0) + 1
    return tally

def build_code_assertions(cards: list, todo: dict) -> dict:
    """代码侧硬判块：把 AGENTS.md 中可确定性比对的规则算成事实，供 Jev 直接采信。

    刻意只做「有明确枚举或账本可依」的判定，不发明判据：
      · illegal_status / illegal_type —— 对照 GOVERNANCE_PROCESS 的受控枚举做**严格相等**。
        红线 5 要求状态枚举纯净，严格相等可同时抓住「核验通过（x）」这类括号小尾巴；
      · pending_cards —— 状态为 待核验 的卡（代码查表即可判，不必问模型）；
      · unmerged_cards —— 已 核验通过 但卡正文「关联提交」仍为 待提交，即尚未合入主干。
        这是区分 awaiting_merge_or_release 与 idle 的唯一可靠判别器：CHANGELOG 日期是
        版本冻结日而非条目写入日，拿日期比较会把「已登记未打 tag」误判成正常维护空闲态；
      · sediment_violations —— 仍留在 todo 表内、但其 ID 已登记进「已流转至」账本的事项，
        即零沉淀纪律被破坏的确定性证据。
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
            if c.get("status") == "核验通过" and c.get("linked_commit") == "待提交"
        ),
        "sediment_violations": sorted(
            {row["id"] for row in rows if row["id"] in transferred}
        ),
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
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_build_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        hint = {
            401: "API Key 无效或未授权（检查 TYPESAFE_API_KEY）",
            403: "无权访问（检查 Key 权限）",
            429: "触发限流，请稍后重试",
        }.get(exc.code, f"HTTP {exc.code}")
        raise RuntimeError(f"TypeSafe API 报错：{hint}\n响应体：{trunc(body, 500)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 TypeSafe API（{TYPESAFE_ENDPOINT}）：{exc}") from exc


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
    for qid, cn in (("pending_verification", "存在待核验卡"),
                    ("sync_complete", "双向同步已完成"),
                    ("zero_sediment_ok", "零沉淀纪律合规")):
        ans = answers.get(qid, {})
        p = ans.get("noul")
        if not _is_num(p):
            print(f"  · {cn} (Noul)：（无有效概率值）")
            continue
        conf = ans.get("confidence")
        if abs(p - 0.5) < NOUL_UNCERTAIN_BAND:
            verdict = "不确定（概率接近 0.5）"
        else:
            verdict = "是" if p >= 0.5 else "否"
        flag = "" if (conf is not None and conf >= CONFIDENCE_GATE) else "  ⚠ 低置信，建议人工复核"
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


def detect_violation(resp: dict, state: dict) -> list:
    """汇总违规证据：代码侧硬校验 + Jev 语义判定，任一命中即违规（红线 7 门禁）。"""
    reasons = []
    ca = state["current_state"]["code_assertions"]
    if ca["illegal_status"]:
        reasons.append(f"状态值非法：{ca['illegal_status']}")
    if ca["illegal_type"]:
        reasons.append(f"类型值非法：{ca['illegal_type']}")
    if ca["sediment_violations"]:
        reasons.append(f"todo 应删未删：{ca['sediment_violations']}")
    answers = resp.get("answers", {})
    for qid, label in (("sync_complete", "双向同步未完成"),
                       ("zero_sediment_ok", "零沉淀纪律被破坏")):
        p = answers.get(qid, {}).get("noul")
        if isinstance(p, (int, float)) and not isinstance(p, bool) and p < 0.5:
            reasons.append(f"{label}（P={p:.2f}）")
    band = compliance_band_value(answers.get("compliance", {}).get("choice"))
    if band is not None and band < COMPLIANCE_VIOLATION_BELOW:
        reasons.append(f"合规档位「{answers['compliance']['choice']}」低于阈值 "
                       f"{COMPLIANCE_VIOLATION_BELOW:g}（代表值 {band:.2f}）")
    if answers.get("current_stage", {}).get("choice") == "has_violation":
        reasons.append("阶段判定为存在治理违规")
    return reasons


def print_recommendation(resp: dict, reasons: list) -> None:
    print("── 建议下一步 ──────────────────────────────────────────")
    if reasons:
        print("  检测到治理违规：" + "；".join(reasons))
        print("  按 AGENTS.md 红线 7『违规即阻断』：存在治理违规不得合入主干，"
              "请先按上方事实定位修复，再重跑本自检。")
        print("")
        return
    answers = resp.get("answers", {})
    stage = answers.get("current_stage", {}).get("choice")
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
    if not isinstance(stage, dict) or not stage.get("choice"):
        return "current_stage.choice 缺失"
    for qid in ("sync_complete", "zero_sediment_ok"):
        ans = answers.get(qid)
        if not isinstance(ans, dict) or not _is_num(ans.get("noul")):
            return f"{qid}.noul 缺失或非数值"
    comp = answers.get("compliance")
    choice = comp.get("choice") if isinstance(comp, dict) else None
    if choice not in COMPLIANCE_BAND_OF:
        return (f"compliance.choice 缺失或不在受控档位内"
                f"（应为 {list(COMPLIANCE_BAND_OF)} 之一）")
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
                        help="TypeSafe API Key（默认读环境变量 TYPESAFE_API_KEY）。")
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
        print("（--offline：已跳过 Jev 调用。设置 TYPESAFE_API_KEY 后去掉该 flag 即启用语义判定。）")
        return 0
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
    print_recommendation(resp, reasons)
    return 4 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
