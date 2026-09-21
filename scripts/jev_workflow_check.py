#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jev_workflow_check.py — 用 TypeSafe 的 Jev（System One 模型）检查 QTVictory
文档治理工作流的状态。

设计原则（分层，遵循 TypeSafe "代码掌流程、模型给语义判断" 的指引）：
  · 确定性采集交给代码：解析变更卡/todo/CHANGELOG/design 头部、git 状态，
    得到"事实"（facts）。查表、计数、状态比对本就是代码擅长的硬逻辑。
  · 语义判定交给 Jev：把「项目文档治理流程」+「当前采集到的状态」作为 state，
    用 typed questions（Choice / Noul / Score）让 Jev 判断——
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

退出码：0 正常；2 缺 key / 参数问题；3 采集或网络/API 失败。
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

# 合规 Score 等级 -> 人类可读标签
COMPLIANCE_LABELS = {
    0: "存在明确违规",
    1: "基本合规但有关键环节缺失或存疑",
    2: "完全符合治理流程",
}


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
            "② docs/devel/design/ 新增或修订章节（状态 讨论中 → 评审通过 → 现行基线）；"
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
    "report_conclusion_enum": ["通过", "受限通过", "未通过"],
    "zero_sediment_rule": (
        "todo 事项一旦落入 change/（建 C 卡）或 design/（更新基线），"
        "必须立即从 todo 表格物理删除，不留 [x] 历史勾选；闭环与审计由 change/design 承载。"
    ),
    "anchor_discipline": (
        "章节号只增不插中间；废弃章节原位保留并标注 [已废弃]，编号不复用；"
        "跨文档引用优先『文档 + 版本 + 节号』三元组。"
    ),
    "merge_gate": "核验通过后才允许合入主干；CHANGELOG 版本条目合入主干时打对应 vX.Y.Z tag。",
    "metadata_contract": (
        "文档头部引用块：**键名**: 值 ｜ 键值，半角冒号加单空格、全角竖线分隔；"
        "状态枚举纯净（禁括号小尾巴）；日期 ISO YYYY-MM-DD。"
    ),
}


# 发给 Jev 的 typed questions（一次 fan-out，互不依赖、并行求值）
QUESTIONS = {
    "current_stage": {
        "type": "choice",
        "instructions": (
            "根据 `governance_process.two_entry_flows.bug_fix` 定义的变更核验流，"
            "判断 `current_state` 目前整体处于哪个阶段。以 `current_state.latest_change_card` "
            "的状态与 `governance_process.bidirectional_sync_points` 的完成情况为主要依据。"
        ),
        "criteria": {
            "idle": "没有进行中的变更：所有 C 卡均已 核验通过 且双向同步与收尾完成",
            "awaiting_verification": "存在 待核验 状态的 C 卡，等待人工会话确认与 AI 代签",
            "awaiting_bidirectional_sync": (
                "存在 核验通过 的 C 卡，但双向同步点（design 原位回链 / design 头部关联变更 / "
                "CHANGELOG 互链）尚未全部完成"
            ),
            "awaiting_merge_or_release": "C 卡已 核验通过 且同步完成，待合入主干或纳入版本打 tag",
            "has_violation": "存在治理违规：状态值非法、todo 零沉淀被破坏、或应删事项残留",
        },
    },
    "pending_verification": {
        "type": "noul",
        "instructions": "`current_state.change_cards` 中是否存在状态为『待核验』的变更卡？",
        "criteria": {
            "true": "至少有一张 C 卡状态为 待核验",
            "false": "没有 待核验 状态的 C 卡",
        },
    },
    "sync_complete": {
        "type": "noul",
        "instructions": (
            "针对 `current_state.latest_change_card`（最新一张已 核验通过 的卡），"
            "`governance_process.bidirectional_sync_points` 列出的同步点是否均已完成？"
            "需核对该卡正文清单、`current_state.design_docs` 头部的『关联变更』、"
            "以及 `current_state.changelog` 是否已登记并互链该卡。"
        ),
        "criteria": {
            "true": "所有双向同步点均已完成",
            "false": "仍有同步点缺失",
        },
    },
    "zero_sediment_ok": {
        "type": "noul",
        "instructions": (
            "对照 `governance_process.zero_sediment_rule`："
            "`current_state.todo_now` 与 `current_state.todo_future` 中是否"
            "没有『已建 C 卡或已立项、本应被物理删除却仍残留』的事项？"
        ),
        "criteria": {
            "true": "todo 表格无应删未删残留，零沉淀纪律得到遵守",
            "false": "存在已建卡/已立项但仍残留在 todo 的事项",
        },
    },
    "compliance": {
        "type": "score",
        "instructions": "综合 `governance_process` 的全部规则，评判 `current_state` 的整体合规程度。",
        "criteria": [
            "存在明确违规：状态值非法、已核验通过但未同步、或 todo 零沉淀被破坏",
            "基本合规但有关键环节缺失或存疑，需人工确认",
            "完全符合治理流程，无待办同步项",
        ],
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

def gather_change_cards(repo: Path) -> list:
    cards = []
    change_dir = repo / "docs/devel/change"
    for path in sorted(change_dir.glob("C*.md")):
        if path.name.lower() == "template.md":
            continue
        fields = parse_header_fields(path.read_text(encoding="utf-8"))
        cards.append({
            "id": fields.get("卡片ID") or path.stem.split("-")[0],
            "type": fields.get("类型"),
            "status": fields.get("状态"),
            "created": fields.get("创建日期"),
            "linked_design": fields.get("关联设计"),
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


def gather_todo(repo: Path) -> dict:
    out = {}
    for name in ("now.md", "future.md"):
        path = repo / "docs/devel/todo" / name
        rows = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s.startswith("|"):
                    continue
                # 跳过分隔行 |---|---|
                if re.match(r"^\|[\s:\-|]+\|$", s):
                    continue
                cells = [c.strip() for c in s.strip("|").split("|")]
                if not cells:
                    continue
                first = cells[0]
                # 仅采集待办 ID 行（BG/EN/FT/TD-编号），过滤表头、占位行与 Phase 路线图等其它表格
                if not re.match(r"^(BG|EN|FT|TD)-\d{4}$", first):
                    continue
                desc = cells[2] if len(cells) > 2 else (cells[1] if len(cells) > 1 else "")
                rows.append({"id": first, "desc": trunc(desc, 140)})
        out[name.replace(".md", "")] = rows
    return out


def gather_design_docs(repo: Path) -> list:
    docs = []
    design_dir = repo / "docs/devel/design"
    if not design_dir.is_dir():
        return docs
    for path in sorted(design_dir.glob("*.md")):
        fields = parse_header_fields(path.read_text(encoding="utf-8"))
        docs.append({
            "file": path.name,
            "version": fields.get("版本"),
            "status": fields.get("状态"),
            "linked_changes": fields.get("关联变更"),
        })
    return docs


def gather_git(repo: Path) -> dict:
    def run(args):
        try:
            return subprocess.run(args, cwd=repo, capture_output=True,
                                  text=True, timeout=15).stdout
        except Exception:
            return ""

    porcelain = run(["git", "status", "--porcelain"])
    files = [ln[3:] for ln in porcelain.splitlines() if ln.strip()]
    return {
        "uncommitted_count": len(files),
        "uncommitted_files": files[:20],
        "last_commit": run(["git", "log", "-1", "--format=%h %s"]).strip(),
    }


def build_state(repo: Path) -> dict:
    cards = gather_change_cards(repo)
    return {
        "governance_process": GOVERNANCE_PROCESS,
        "current_state": {
            "change_cards": cards,
            "change_card_count": len(cards),
            "status_tally": _tally(cards),
            "latest_verified_card": latest_verified_card(repo, cards),
            "todo_now": gather_todo(repo)["now"],
            "todo_future": gather_todo(repo)["future"],
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
    cs = state["current_state"]
    tally = cs["status_tally"]
    tally_str = "、".join(f"{k}×{v}" for k, v in tally.items()) or "无"
    print("── 采集事实（代码确定性采集）────────────────────────────")
    print(f"  变更卡总数：{cs['change_card_count']}    状态分布：{tally_str}")
    lvc = cs["latest_verified_card"]
    if lvc:
        print(f"  最新已核验通过卡：{lvc['id']}（{lvc.get('type')}，{lvc.get('created')}）")
    else:
        print("  最新已核验通过卡：无")
    cl = cs["changelog"]
    if cl:
        print(f"  CHANGELOG 顶部版本：[{cl.get('version')}] - {cl.get('date')}")
    now_ids = [r["id"] for r in cs["todo_now"]]
    fut_ids = [r["id"] for r in cs["todo_future"]]
    print(f"  todo/now 残留事项：{now_ids or '无'}")
    print(f"  todo/future 残留事项：{fut_ids or '无'}")
    git = cs["git"]
    print(f"  git 未提交文件数：{git['uncommitted_count']}    最近提交：{git['last_commit'] or '无'}")
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

    # Noul 三连
    for qid, cn in (("pending_verification", "存在待核验卡"),
                    ("sync_complete", "双向同步已完成"),
                    ("zero_sediment_ok", "零沉淀纪律合规")):
        ans = answers.get(qid, {})
        p = ans.get("noul")
        if p is None:
            continue
        if abs(p - 0.5) < NOUL_UNCERTAIN_BAND:
            verdict = "不确定（概率接近 0.5）"
        else:
            verdict = "是" if p >= 0.5 else "否"
        print(f"  · {cn} (Noul)：{verdict}  [P(yes)={p:.2f}]")

    # Score: 整体合规
    comp = answers.get("compliance", {})
    if "score" in comp:
        score = comp["score"]
        level = COMPLIANCE_LABELS.get(int(round(score)), f"level {score}")
        conf = comp.get("confidence")
        flag = "" if (conf is not None and conf >= CONFIDENCE_GATE) else "  ⚠ 低置信，建议人工复核"
        print(f"  · 整体合规 (Score)：{score:.2f} → {level}  [置信 {_fmt_conf(conf)}]{flag}")
    print("")


def print_recommendation(resp: dict) -> None:
    answers = resp.get("answers", {})
    stage = answers.get("current_stage", {}).get("choice")
    print("── 建议下一步 ──────────────────────────────────────────")
    tips = {
        "awaiting_verification": "有卡待核验：跑测试命令并在会话向人工汇报事实，人工确认后由 AI 代签收口。",
        "awaiting_bidirectional_sync": "已核验通过但同步未闭环：补齐 design 原位回链 / 头部关联变更 / CHANGELOG 互链 / 版本号。",
        "awaiting_merge_or_release": "已核验通过且已同步：可合入主干，纳入版本时打 vX.Y.Z tag。",
        "has_violation": "检测到治理违规：按上文 Noul/Score 定位违规点，优先修复后再合入。",
        "idle": "无进行中变更：治理流处于干净检查点。",
    }
    print(f"  {tips.get(stage, '（无明确建议）')}")
    print("")


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

    print_jev_answers(resp)
    print_recommendation(resp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
