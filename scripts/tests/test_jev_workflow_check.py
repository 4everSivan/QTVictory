"""scripts/jev_workflow_check.py 的回归测试。

覆盖 C023 / C024 修复的缺陷，每一类都对应一个曾经真实发生过的失效模式：
  1. 流转账本复合记录错配 / 漏记（EN-0002 整条消失、EN-0003 错配到 C002）
  5. cross_check 缺失导致阶段判定与代码事实矛盾时可静默放行
  6. call_jev 三类异常逃逸成 exit 1
  7. cross_check 对每条事实各设约束，待核验 + 已核验未合入并存时自相矛盾，
     把本仓库的正常中间态误拦成 exit 4（改为 expected_stage 取最早未完成步骤）
  8. 低置信语义判定被当硬判据：合规档位分布接近平手（0.44 vs 0.42）时误拦，
     违背 AGENTS.md「低置信需人工复核」（改为退出码 6 转人工）
  9. noul 题无 confidence 字段却常驻 ⚠ 低置信噪音，把提示稀释成背景音
  10. noul 判罚用裸 p < 0.5、不看展示层尊重的 NOUL_UNCERTAIN_BAND，答案行写
     「不确定」而结论行写「仍有同步点缺失」，同一份概率两层给出相反定性
  11. 不确定带 ±0.15 对模型噪声过窄：同输入实跑 P=0.33~0.42 横跨下沿，
     干净仓库被误拦 exit 4，而真实违规仅 P=0.06，两侧本有空档可切
  12. cross_check 把 awaiting_bidirectional_sync 的放行权绑在 unmerged_cards
     非空上：全部卡合入后 expected 退化为 idle，Jev 对同步闭环的低置信猜疑反被
     升级成 exit 4——而 unmerged_cards 为空正是每次正常收口后的必经路径，等于
     每个干净检查点都被误拦一次（改为无条件放行；真实未闭环由 sync_complete
     noul 门禁与 compliance 档位闸独立兜住，不依赖本放行集）

运行：python3 -m pytest scripts/tests -q
"""

import json
import os
import subprocess
import urllib.error
import pytest

import jev_workflow_check as jwc


# ---------------------------------------------------------------------------
#  fixtures / helpers
# ---------------------------------------------------------------------------

def _card(cid, status="核验通过", ctype="BugFix", commit="abc1234"):
    return {
        "id": cid,
        "status": status,
        "type": ctype,
        "linked_commit": commit,
        "created": "2026-09-21",
        "linked_design": "",
    }


def _empty_assertions(**over):
    base = {
        "illegal_status": [],
        "illegal_type": [],
        "pending_cards": [],
        "unmerged_cards": [],
        "sediment_violations": [],
        "frozen_dir_dirty": False,
    }
    base.update(over)
    return base
def _consistent_state():
    """与 `_good_response()` 的阶段判定自洽的状态：C022 已核验通过但尚未合入。

    必须自洽：`cross_check` 会拿 expected_stage() 比对立项，状态与响应各说各话
    就会制造矛盾理由，让「本应无违规」的用例失败。
    """
    return _state(code_assertions=_empty_assertions(unmerged_cards=["C022"]))

def _state(**over):
    cs = {
        "change_cards": [],
        "code_assertions": _empty_assertions(),
        "latest_verified_card": None,
        "todo_now": [],
        "todo_future": [],
        "todo_transferred": {},
        "changelog": {},
        "design_docs": [],
        "git": {"last_commit": "abc1234", "frozen_dir_dirty": False},
    }
    cs.update(over)
    return {"current_state": cs}


def _good_response(**over):
    """一份结构完整、可顺利通过 validate_response 的响应。

    各 noul 默认值必须明确落在不确定带之外（P 距 0.5 不小于 NOUL_UNCERTAIN_BAND），
    因为这份夹具代表"干净检查点"：任何一题落入带内都会变成人工复核项，
    「本应无违规」的用例会随之失败。改默认值前先看 NOUL_UNCERTAIN_BAND。
    """
    ans = {
        "current_stage": {"choice": "awaiting_merge_or_release", "confidence": 0.9},
        "pending_verification": {"noul": 0.1},
        "sync_complete": {"noul": 0.9},
        "zero_sediment_ok": {"noul": 0.9},
        "compliance": {"choice": "整体合规，个别待办", "confidence": 0.9},
    }
    ans.update(over)
    return {"answers": ans}


def _write_todo(repo, now_text, future_text=""):
    d = repo / "docs" / "devel" / "todo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "now.md").write_text(now_text, encoding="utf-8")
    (d / "future.md").write_text(future_text, encoding="utf-8")


NOW_HEADER = "| ID | 模块 | 缺陷现象与复现线索 | 严重度 | 登记日期 | 拟流转目标 | 来源/备注 |\n"
NOW_SEP = "|---|---|---|---|---|---|---|\n"


def _now_row(rid, target):
    return f"| {rid} | 模块 | 现象 | 高 | 2026-09-01 | {target} | 来源 |\n"


# ---------------------------------------------------------------------------
#  1. 流转账本：复合记录必须按位配对，一条都不能漏
# ---------------------------------------------------------------------------

class TestTransferLedger:
    @pytest.mark.parametrize("link", [
        "[C002]/[C003]",                                        # 纯方括号
        "[C002](../change/C002-x.md)/[C003](../change/C003-y.md)",  # 带 url
        "[C002](../a/b.md)、[C003](../c/d.md)",                  # 顿号分隔
        "[C002](x)/[C003]",                                     # 一侧有 url
    ], ids=["plain", "url", "dunhao", "mixed"])
    def test_compound_record_pairs_positionally(self, tmp_path, link):
        _write_todo(tmp_path, NOW_HEADER + NOW_SEP + "\n"
                    f"> 📌 **流转纪律**：EN-0002/EN-0003 已流转至 {link} 并移出。\n")
        led = jwc.gather_todo(tmp_path)["transferred"]
        assert led == {"EN-0002": "C002", "EN-0003": "C003"}

    def test_single_record_with_url(self, tmp_path):
        _write_todo(tmp_path, NOW_HEADER + NOW_SEP + "\n"
                    "> 📌 EN-0010 已流转至 [C022](../change/C022-x.md) 并移出。\n")
        assert jwc.gather_todo(tmp_path)["transferred"] == {"EN-0010": "C022"}

    def test_legacy_dashless_source(self, tmp_path):
        """遗留的无连字符形态 C001 已流转至 [C001] 也必须入账。"""
        _write_todo(tmp_path, NOW_HEADER + NOW_SEP + "\n"
                    "> 📌 C001 已流转至 [C001](../change/C001-x.md) 并移出。\n")
        assert jwc.gather_todo(tmp_path)["transferred"] == {"C001": "C001"}

    def test_surplus_sources_take_last_target(self, tmp_path):
        """个数不齐时宁多记不漏记：多出的源事项挂最后一个落点。"""
        _write_todo(tmp_path, NOW_HEADER + NOW_SEP + "\n"
                    "> 📌 EN-0001/EN-0002/EN-0003 已流转至 [C002] 并移出。\n")
        led = jwc.gather_todo(tmp_path)["transferred"]
        assert led == {"EN-0001": "C002", "EN-0002": "C002", "EN-0003": "C002"}

    def test_records_separated_by_fullwidth_semicolon_stay_independent(self, tmp_path):
        """`；` 分隔的两条独立记录不能被并成一条复合记录。"""
        _write_todo(tmp_path, NOW_HEADER + NOW_SEP + "\n"
                    "> 📌 EN-0006 已流转至 [C008](../a.md) 并移出；"
                    "EN-0007 已流转至 [C012](../b.md) 并移出。\n")
        assert jwc.gather_todo(tmp_path)["transferred"] == {
            "EN-0006": "C008", "EN-0007": "C012"}

    def test_non_link_prose_is_not_recorded(self, tmp_path):
        """「已流转至 C022 相关章节」这类非链接叙述不得入账。"""
        _write_todo(tmp_path, NOW_HEADER + NOW_SEP + "\n"
                    "> 📌 EN-0006 已流转至 C022 相关章节。\n")
        assert jwc.gather_todo(tmp_path)["transferred"] == {}

    def test_target_column_detected_by_name(self, tmp_path):
        """future.md 的列名叫「拟落地方向」，不能靠硬编码列序。"""
        head = ("| ID | 模块/标的 | 需求概述与核心语义 | 优先级 | 登记日期 "
                "| 拟落地方向 | 来源/参考 |\n")
        _write_todo(tmp_path, NOW_HEADER + NOW_SEP,
                    head + "|---|---|---|---|---|---|---|\n"
                    "| FT-0001 | 标的 | 需求 | 高 | 2026-09-01 | design 02 §6.1 | ref |\n")
        rows = jwc.gather_todo(tmp_path)["future"]
        assert [r["id"] for r in rows] == ["FT-0001"]
        assert rows[0]["target_kind"] == "design"

    def test_real_repo_compound_pairing(self):
        """真实仓库回归：C023 之前 EN-0002 漏记、EN-0003 错配到 C002。"""
        led = jwc.gather_todo(jwc.find_repo_root())["transferred"]
        assert led.get("EN-0002") == "C002"
        assert led.get("EN-0003") == "C003"
        # 账本本身是 dict，键唯一；条目数不应少于两条独立记录
        assert len(led) >= 2


# ---------------------------------------------------------------------------
#  2. build_code_assertions
# ---------------------------------------------------------------------------

class TestCodeAssertions:
    def test_illegal_status_catches_bracket_tail(self):
        cards = [_card("C001", status="核验通过（x）")]
        ca = jwc.build_code_assertions(cards, {"now": [], "future": [], "transferred": {}})
        assert ca["illegal_status"] == ["C001"]

    def test_illegal_type(self):
        cards = [_card("C001", ctype="BugFix ")]
        ca = jwc.build_code_assertions(cards, {"now": [], "future": [], "transferred": {}})
        assert ca["illegal_type"] == ["C001"]

    def test_pending_cards_is_stage_discriminator_not_violation(self):
        cards = [_card("C023", status="待核验")]
        ca = jwc.build_code_assertions(cards, {"now": [], "future": [], "transferred": {}})
        assert ca["pending_cards"] == ["C023"]

    @pytest.mark.parametrize("commit,expected_unmerged", [
        ("待提交", True),          # 字面量占位
        ("2c5955f", False),        # 短 hash
        ("2c5955f0e1b7c4a9d3f6e8b1c5a7d9e0f1b3c5d7", False),  # 完整 hash
        ("abc1234 (squash)", True),  # 带后缀的变体：不是纯 hash
        ("", True),                # 空串
        (None, True),              # 未填
    ], ids=["placeholder", "short-hash", "full-hash", "squash-suffix", "empty", "none"])
    def test_unmerged_cards_uses_hash_shape(self, commit, expected_unmerged):
        cards = [_card("C022", commit=commit)]
        ca = jwc.build_code_assertions(cards, {"now": [], "future": [], "transferred": {}})
        assert bool(ca["unmerged_cards"]) is expected_unmerged

    def test_sediment_violations(self):
        todo = {
            "now": [{"id": "EN-0010", "desc": "d", "target": "change", "target_kind": "change"}],
            "future": [],
            "transferred": {"EN-0010": "C022"},
        }
        ca = jwc.build_code_assertions([], todo)
        assert ca["sediment_violations"] == ["EN-0010"]

    def test_frozen_dir_dirty_flag_propagates(self):
        todo = {"now": [], "future": [], "transferred": {}}
        assert jwc.build_code_assertions([], todo)["frozen_dir_dirty"] is False
        assert jwc.build_code_assertions([], todo, frozen_dir_dirty=True)["frozen_dir_dirty"] is True


# ---------------------------------------------------------------------------
#  3. validate_response：畸形形状必须判无效，而不是留到打印阶段崩成 exit 1
# ---------------------------------------------------------------------------

class TestValidateResponse:
    def test_well_formed_passes(self):
        assert jwc.validate_response(_good_response()) is None

    @pytest.mark.parametrize("resp,why", [
        (None, "非对象"),
        ([], "列表"),
        ("{}", "字符串"),
        ({}, "缺少 answers"),
        ({"answers": []}, "answers 非字典"),
        ({"answers": {}}, "answers 为空"),
        ({"answers": {"current_stage": {"choice": "idle"}}}, "缺大题"),
    ], ids=["none", "list", "str", "no-answers", "answers-list", "answers-empty", "missing-q"])
    def test_structural_defects(self, resp, why):
        assert jwc.validate_response(resp) is not None, why

    def test_stage_choice_out_of_enum(self):
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = "whatever"
        assert jwc.validate_response(r) is not None

    @pytest.mark.parametrize("qid", ["pending_verification", "sync_complete", "zero_sediment_ok"])
    def test_noul_missing_or_non_numeric(self, qid):
        r = _good_response()
        del r["answers"][qid]["noul"]
        assert jwc.validate_response(r) is not None
        r = _good_response()
        r["answers"][qid]["noul"] = "0.7"
        assert jwc.validate_response(r) is not None

    def test_compliance_choice_out_of_bands(self):
        r = _good_response()
        r["answers"]["compliance"]["choice"] = "还行"
        assert jwc.validate_response(r) is not None

    def test_confidence_non_numeric_is_rejected(self):
        """print_jev_answers 会做 f"{v:.2f}"，字符串 confidence 必须在此拦下。"""
        r = _good_response()
        r["answers"]["current_stage"]["confidence"] = "high"
        assert jwc.validate_response(r) is not None

    def test_probabilities_list_is_rejected(self):
        r = _good_response()
        r["answers"]["current_stage"]["probabilities"] = [0.1, 0.9]
        assert jwc.validate_response(r) is not None

    def test_probabilities_value_non_numeric_is_rejected(self):
        r = _good_response()
        r["answers"]["current_stage"]["probabilities"] = {"idle": "high"}
        assert jwc.validate_response(r) is not None

    def test_probabilities_none_is_tolerated(self):
        r = _good_response()
        r["answers"]["current_stage"]["probabilities"] = None
        assert jwc.validate_response(r) is None


# ---------------------------------------------------------------------------
#  4. detect_violation / cross_check
# ---------------------------------------------------------------------------

class TestDetectViolation:
    def test_clean_state_has_no_reason(self):
        assert jwc.detect_violation(_good_response(), _consistent_state()) == []

    def test_code_side_reasons_fire_offline(self):
        st = _state(code_assertions=_empty_assertions(
            illegal_status=["C001"], illegal_type=["C002"],
            sediment_violations=["EN-0010"], frozen_dir_dirty=True))
        reasons = jwc.detect_violation({}, st)
        assert len(reasons) == 4

    @pytest.mark.parametrize("qid,prob,should_fire", [
        ("sync_complete", 0.1, True),
        ("sync_complete", 0.7, False),
        ("zero_sediment_ok", 0.1, True),
        ("zero_sediment_ok", 0.9, False),
    ])
    def test_noul_polarity(self, qid, prob, should_fire):
        r = _good_response(**{qid: {"noul": prob}})
        reasons = jwc.detect_violation(r, _consistent_state())
        assert bool(reasons) is should_fire

    def test_pending_verification_is_not_a_violation_by_itself(self):
        """待核验是流程中间态而非违规：单靠该题高概率不得触发门禁，
        它与阶段的矛盾由 cross_check 收口（见 TestCrossCheck）。"""
        r = _good_response(**{"pending_verification": {"noul": 0.95}})
        assert jwc.detect_violation(r, _consistent_state()) == []

    @pytest.mark.parametrize("qid", ["sync_complete", "zero_sediment_ok"])
    @pytest.mark.parametrize("prob", [0.30, 0.5, 0.70])
    def test_noul_in_uncertain_band_is_not_a_hard_reason(self, qid, prob):
        """概率落入不确定带（|P-0.5| < NOUL_UNCERTAIN_BAND）时，展示层把该题标为
        「不确定」；门禁层就不能反过来写确定性结论，否则答案行与结论行自相矛盾。
        此类判定转 semantic_review_items 交人工复核（exit 6）。"""
        r = _good_response(**{qid: {"noul": prob}})
        assert jwc.detect_violation(r, _consistent_state()) == []

    @pytest.mark.parametrize("qid,prob,should_fire", [
        ("sync_complete", 0.10, True),
        ("sync_complete", 0.24, True),
        ("sync_complete", 0.30, False),
        ("sync_complete", 0.45, False),
        ("sync_complete", 0.80, False),
        ("zero_sediment_ok", 0.10, True),
        ("zero_sediment_ok", 0.24, True),
        ("zero_sediment_ok", 0.30, False),
        ("zero_sediment_ok", 0.45, False),
        ("zero_sediment_ok", 0.80, False),
    ])
    def test_noul_outside_band_still_gates(self, qid, prob, should_fire):
        """带外一律照旧门禁：明确判否（P 低于 0.5 且越出不确定带）即违规。
        真实沉淀违规实跑 P=0.06 落在这一侧，必须继续硬拦。"""
        r = _good_response(**{qid: {"noul": prob}})
        assert bool(jwc.detect_violation(r, _consistent_state())) is should_fire

    @pytest.mark.parametrize("qid", ["sync_complete", "zero_sediment_ok"])
    @pytest.mark.parametrize("prob,should_fire", [
        (0.24, True),    # 距 0.5 为 0.26，刚越出带外沿 → 拦
        (0.25, True),    # 距 0.5 恰为带宽：判定用严格小于，踩线不算不确定 → 拦
        (0.26, False),   # 距 0.5 为 0.24，带内 → 转人工复核
        (0.5, False),
    ])
    def test_noul_band_boundary_is_inclusive_of_uncertainty(self, qid, prob, should_fire):
        """边界按严格小于判：|P-0.5| == NOUL_UNCERTAIN_BAND 时仍算带外、照旧门禁。
        三个用例只差 0.02，用来锁死带宽语义不被无意改窄——干净仓库实跑噪声
        P=0.33~0.42 必须落在带内，真实违规 P=0.06 必须落在带外。"""
        r = _good_response(**{qid: {"noul": prob}})
        assert bool(jwc.detect_violation(r, _consistent_state())) is should_fire

    @pytest.mark.parametrize("band,should_fire", [
        ("存在明确违规", True),
        ("有关键环节缺失或存疑", True),
        ("基本合规，轻微瑕疵", False),
        ("整体合规，个别待办", False),
        ("完全符合治理流程", False),
    ])
    def test_compliance_band_threshold(self, band, should_fire):
        r = _good_response()
        r["answers"]["compliance"]["choice"] = band
        reasons = jwc.detect_violation(r, _consistent_state())
        assert bool(reasons) is should_fire, band

    def test_band_boundary_is_not_a_violation(self):
        """阈值是「低于即违规」；恰好落在阈值上的「基本合规」档不拦。"""
        assert jwc.COMPLIANCE_VIOLATION_BELOW == 0.70
        # 关键环节缺失/存疑（0.50）在阈值之下 → 拦；基本合规（0.70）踩线 → 放行
        assert jwc.compliance_band_value("有关键环节缺失或存疑") < jwc.COMPLIANCE_VIOLATION_BELOW
        assert not (jwc.compliance_band_value("基本合规，轻微瑕疵") < jwc.COMPLIANCE_VIOLATION_BELOW)

    def test_stage_has_violation(self):
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = "has_violation"
        st = _consistent_state()
        assert "阶段判定为存在治理违规" in jwc.detect_violation(r, st)[0] or \
            any("存在治理违规" in x for x in jwc.detect_violation(r, st))

    def test_low_confidence_compliance_band_is_not_a_hard_reason(self):
        """档位低于阈值但置信 0.31：按 AGENTS.md 降级为人工复核，
        不进硬判据——否则误拦正常中间态。"""
        r = _good_response()
        r["answers"]["compliance"] = {"choice": "有关键环节缺失或存疑", "confidence": 0.31}
        assert jwc.detect_violation(r, _consistent_state()) == []

    def test_low_confidence_stage_has_violation_is_not_a_hard_reason(self):
        r = _good_response()
        r["answers"]["current_stage"] = {"choice": "has_violation", "confidence": 0.42}
        assert jwc.detect_violation(r, _state()) == []

    def test_low_confidence_stage_skips_cross_check(self):
        """cross_check 由 current_stage 派生；阶段判定本身低置信时无从校验。"""
        st = _state(code_assertions=_empty_assertions(pending_cards=["C023"]))
        r = _good_response()
        r["answers"]["current_stage"] = {"choice": "idle", "confidence": 0.3}
        assert jwc.detect_violation(r, st) == []


class TestCrossCheck:
    def test_no_stage_returns_empty(self):
        assert jwc.cross_check({}, _state()) == []
        assert jwc.cross_check({"answers": {}}, _state()) == []

    # awaiting_bidirectional_sync 不在此列：同步闭环是代码侧无法否证的语义判断，
    # C024 起无条件放行（见 cross_check 注释），有无待核验卡都不影响。
    @pytest.mark.parametrize("stage", [
        "idle", "awaiting_merge_or_release"])
    def test_pending_card_contradicts_stage(self, stage):
        st = _state(code_assertions=_empty_assertions(pending_cards=["C023"]))
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = stage
        reasons = jwc.cross_check(r, st)
        assert len(reasons) == 1
        assert "C023" in reasons[0]

    @pytest.mark.parametrize(
        "stage", ["awaiting_verification", "awaiting_bidirectional_sync", "has_violation"])
    def test_pending_card_consistent_stage(self, stage):
        st = _state(code_assertions=_empty_assertions(pending_cards=["C023"]))
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = stage
        assert jwc.cross_check(r, st) == []

    @pytest.mark.parametrize("stage", ["idle", "awaiting_verification"])
    def test_unmerged_card_contradicts_stage(self, stage):
        st = _state(code_assertions=_empty_assertions(unmerged_cards=["C022"]))
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = stage
        reasons = jwc.cross_check(r, st)
        assert len(reasons) == 1
        assert "C022" in reasons[0]

    @pytest.mark.parametrize("stage", [
        "awaiting_bidirectional_sync", "awaiting_merge_or_release", "has_violation"])
    def test_unmerged_card_consistent_stage(self, stage):
        st = _state(code_assertions=_empty_assertions(unmerged_cards=["C022"]))
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = stage
        assert jwc.cross_check(r, st) == []

    def test_overlapping_cards_expect_earliest_unfinished_step(self):
        """本仓库的常态：新卡待核验 + 上一张已核验未合入并存。
        expected_stage 取最早未完成步骤（awaiting_verification），Jev 判该阶段
        必须放行——两条独立约束会自相矛盾，把正常中间态误拦成 exit 4。"""
        ca = _empty_assertions(pending_cards=["C023"], unmerged_cards=["C022"])
        st = _state(code_assertions=ca)
        assert jwc.expected_stage(ca) == "awaiting_verification"
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = "awaiting_verification"
        assert jwc.cross_check(r, st) == []

    def test_has_violation_is_always_allowed(self):
        """模型判出代码侧没发现的违规时不得反被 cross_check 拦——方向从严。"""
        st = _state()
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = "has_violation"
        assert jwc.cross_check(r, st) == []

    @pytest.mark.parametrize("fact", [
        "illegal_status", "illegal_type", "sediment_violations", "frozen_dir_dirty"])
    def test_violation_facts_expect_has_violation(self, fact):
        ca = _empty_assertions(**{fact: True if fact == "frozen_dir_dirty" else ["C022"]})
        st = _state(code_assertions=ca)
        assert jwc.expected_stage(ca) == "has_violation"
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = "has_violation"
        assert jwc.cross_check(r, st) == []

    def test_all_merged_expects_idle(self):
        assert jwc.expected_stage(_empty_assertions()) == "idle"

    def test_all_closed_state_allows_sync_suspicion(self):
        """缺陷 22（C024）：全部卡已合入时 expected 退化为 idle，而同步闭环是代码侧
        两个方向都裁不了的语义判断（design 原位回链 / 头部关联变更 / CHANGELOG 互链
        都要读正文才能确认）。一旦因为 unmerged_cards 为空就不放行该标签，Jev 对同步
        闭环的低置信猜疑就会被升级成 exit 4 硬违规——而 unmerged_cards 为空正是每次
        正常收口后的必经路径，等于每个干净检查点都会被误拦一次。干净检查点被拦会训练
        运营者忽略退出码，这比漏拦更危险。真实未闭环仍由 sync_complete noul 门禁与
        compliance 档位闸独立兜住，不依赖本放行集。"""
        st = _state()
        assert jwc.expected_stage(st["current_state"]["code_assertions"]) == "idle"
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = "awaiting_bidirectional_sync"
        assert jwc.cross_check(r, st) == []
        assert jwc.detect_violation(r, st) == []

    @pytest.mark.parametrize(
        "stage", ["awaiting_verification", "awaiting_merge_or_release"])
    def test_no_open_step_contradicts_stage(self, stage):
        """放行 awaiting_bidirectional_sync 不等于放开其余标签：没有任何未完成
        步骤却判成还在等核验 / 等合入，仍是代码侧能否证的矛盾，必须继续拦。"""
        st = _state()
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = stage
        reasons = jwc.cross_check(r, st)
        assert len(reasons) == 1
        assert jwc.STAGE_LABELS[stage] in reasons[0]

    def test_stage_facts_names_the_driving_evidence(self):
        text = jwc._stage_facts(_empty_assertions(
            pending_cards=["C023"], unmerged_cards=["C022"]))
        assert "C023" in text and "C022" in text


class TestSemanticReview:
    """低置信语义判定必须转人工复核，而不是当硬判据或静默通过。"""

    def test_clean_response_has_no_review_item(self):
        assert jwc.semantic_review_items(_good_response()) == []

    def test_low_confidence_compliance_is_listed(self):
        r = _good_response()
        r["answers"]["compliance"] = {"choice": "有关键环节缺失或存疑", "confidence": 0.31}
        items = jwc.semantic_review_items(r)
        assert len(items) == 1
        assert "整体合规" in items[0] and "0.31" in items[0]

    def test_stage_item_uses_human_label(self):
        r = _good_response()
        r["answers"]["current_stage"] = {"choice": "has_violation", "confidence": 0.52}
        items = jwc.semantic_review_items(r)
        assert len(items) == 1
        assert "当前阶段" in items[0]
        assert jwc.STAGE_LABELS["has_violation"] in items[0]

    def test_noul_without_confidence_is_not_reviewed(self):
        """noul 题没有 confidence 字段，概率是它唯一的信号；带外概率不进复核清单。"""
        r = _good_response(**{"sync_complete": {"noul": 0.2}})
        assert jwc.semantic_review_items(r) == []

    @pytest.mark.parametrize("qid", ["sync_complete", "zero_sediment_ok"])
    @pytest.mark.parametrize("prob", [0.3, 0.5, 0.7])
    def test_noul_in_uncertain_band_is_reviewed(self, qid, prob):
        """带内概率是"模型自己也没定夺"：不进硬判据，但必须进复核清单（exit 6）。"""
        r = _good_response(**{qid: {"noul": prob}})
        items = jwc.semantic_review_items(r)
        assert len(items) == 1
        assert jwc.NOUL_LABELS[qid] in items[0]
        assert "概率落入不确定带" in items[0]

    def test_offline_empty_response_has_no_review_item(self):
        assert jwc.semantic_review_items({}) == []


class TestPrintJevAnswers:
    """noul 行不再常驻 ⚠ 低置信噪音：无 confidence 字段时明说以概率为准。"""

    def test_noul_without_confidence_says_so(self, capsys):
        jwc.print_jev_answers(_good_response())
        out = capsys.readouterr().out
        assert "noul 型无置信字段，以概率为准" in out
        assert "低置信" not in out

    def test_low_confidence_choice_is_flagged(self, capsys):
        r = _good_response()
        r["answers"]["compliance"] = {"choice": "有关键环节缺失或存疑", "confidence": 0.31}
        jwc.print_jev_answers(r)
        assert "低置信" in capsys.readouterr().out


# ---------------------------------------------------------------------------
#  5. call_jev：所有异常都必须收敛为 RuntimeError（→ exit 3）
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _BrokenBodyHTTPError(urllib.error.HTTPError):
    def read(self, *a, **k):
        raise OSError("connection reset by peer")


def _patch_urlopen(monkeypatch, fn):
    monkeypatch.setattr(jwc.urllib.request, "urlopen", fn)


class TestCallJev:
    def test_success(self, monkeypatch):
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(b'{"answers": {}}'))
        assert jwc.call_jev({}, "k", "jev-latest") == {"answers": {}}

    def test_non_json_body(self, monkeypatch):
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(b"<html>502</html>"))
        with pytest.raises(RuntimeError, match="非 JSON"):
            jwc.call_jev({}, "k", "jev-latest")

    def test_empty_body(self, monkeypatch):
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(b""))
        with pytest.raises(RuntimeError):
            jwc.call_jev({}, "k", "jev-latest")

    def test_http_error(self, monkeypatch):
        def boom(*a, **k):
            raise urllib.error.HTTPError("http://x", 401, "Unauthorized", None, None)
        _patch_urlopen(monkeypatch, boom)
        with pytest.raises(RuntimeError, match="401"):
            jwc.call_jev({}, "k", "jev-latest")

    def test_http_error_with_unreadable_body(self, monkeypatch):
        """exc.read() 自身抛错时也不能逃逸成 exit 1。"""
        def boom(*a, **k):
            raise _BrokenBodyHTTPError("http://x", 500, "Server Error", None, None)
        _patch_urlopen(monkeypatch, boom)
        with pytest.raises(RuntimeError):
            jwc.call_jev({}, "k", "jev-latest")

    def test_url_error(self, monkeypatch):
        def boom(*a, **k):
            raise urllib.error.URLError("connection refused")
        _patch_urlopen(monkeypatch, boom)
        with pytest.raises(RuntimeError, match="无法连接"):
            jwc.call_jev({}, "k", "jev-latest")

    def test_read_timeout(self, monkeypatch):
        """socket.timeout / TimeoutError 不是 URLError 子类，曾逃逸成 exit 1。"""
        def boom(*a, **k):
            raise TimeoutError("timed out")
        _patch_urlopen(monkeypatch, boom)
        with pytest.raises(RuntimeError, match="连接或读取"):
            jwc.call_jev({}, "k", "jev-latest")

    def test_os_error(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("ssl error")
        _patch_urlopen(monkeypatch, boom)
        with pytest.raises(RuntimeError):
            jwc.call_jev({}, "k", "jev-latest")

    def test_unexpected_exception_is_contained(self, monkeypatch):
        def boom(*a, **k):
            raise ValueError("boom")
        _patch_urlopen(monkeypatch, boom)
        with pytest.raises(RuntimeError, match="意外错误"):
            jwc.call_jev({}, "k", "jev-latest")


# ---------------------------------------------------------------------------
#  6. main() 退出码契约
# ---------------------------------------------------------------------------

def _run_main(monkeypatch, argv, state):
    # _repo 只是把仓库根传进 main 的通道，必须先从 state 里摘掉：它会随请求体
    # 一起被 json.dumps，PosixPath 会直接把序列化炸掉（TypeError）。
    repo = state.pop("_repo")
    monkeypatch.setattr(jwc, "find_repo_root", lambda: repo)
    monkeypatch.setattr(jwc, "build_state", lambda _repo: state)
    monkeypatch.setattr("sys.argv", ["jev_workflow_check.py"] + argv)
    return jwc.main()


class TestMainExitCodes:
    def test_json_dumps_payload_and_exits_zero(self, monkeypatch, tmp_path, capsys):
        st = _state()
        st["_repo"] = tmp_path
        assert _run_main(monkeypatch, ["--json"], st) == 0
        payload = json.loads(capsys.readouterr().out)
        assert set(payload) == {"state", "model", "questions"}

    def test_offline_clean_exits_zero(self, monkeypatch, tmp_path, capsys):
        st = _state()
        st["_repo"] = tmp_path
        assert _run_main(monkeypatch, ["--offline"], st) == 0
        out = capsys.readouterr().out
        assert "已跳过 Jev 语义判定" in out
        assert "语义判定被跳过" in out  # 必须讲清离线只过了代码侧硬判

    def test_offline_violation_exits_four(self, monkeypatch, tmp_path, capsys):
        """C023 之前：打印了「非法状态」却 exit 0，红线 7 门禁被绕过。"""
        st = _state(code_assertions=_empty_assertions(illegal_status=["C022"]))
        st["_repo"] = tmp_path
        assert _run_main(monkeypatch, ["--offline"], st) == 4
        assert "非法状态" in capsys.readouterr().out

    def test_offline_frozen_dir_dirty_exits_four(self, monkeypatch, tmp_path):
        st = _state(code_assertions=_empty_assertions(frozen_dir_dirty=True))
        st["_repo"] = tmp_path
        assert _run_main(monkeypatch, ["--offline"], st) == 4

    def test_missing_key_exits_two(self, monkeypatch, tmp_path):
        st = _state()
        st["_repo"] = tmp_path
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        monkeypatch.setattr(jwc, "load_api_key_from_credentials", lambda: None)
        assert _run_main(monkeypatch, [], st) == 2

    def test_api_failure_exits_three(self, monkeypatch, tmp_path):
        st = _state()
        st["_repo"] = tmp_path
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")

        def boom(*a, **k):
            raise urllib.error.URLError("refused")
        _patch_urlopen(monkeypatch, boom)
        assert _run_main(monkeypatch, [], st) == 3

    def test_invalid_response_exits_five(self, monkeypatch, tmp_path):
        st = _state()
        st["_repo"] = tmp_path
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(b'{"answers": {}}'))
        assert _run_main(monkeypatch, [], st) == 5

    def test_violation_response_exits_four(self, monkeypatch, tmp_path):
        st = _state()
        st["_repo"] = tmp_path
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        body = json.dumps(_good_response()).encode("utf-8")
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(body))
        r = _good_response()
        r["answers"]["zero_sediment_ok"]["noul"] = 0.05
        body = json.dumps(r).encode("utf-8")
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(body))
        assert _run_main(monkeypatch, [], st) == 4

    def test_clean_response_exits_zero(self, monkeypatch, tmp_path):
        """干净态：代码侧期望阶段与 Jev 判定一致，且置信度过门禁。"""
        st = _state(code_assertions=_empty_assertions(unmerged_cards=["C022"]))
        st["_repo"] = tmp_path
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        body = json.dumps(_good_response()).encode("utf-8")
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(body))
        assert _run_main(monkeypatch, [], st) == 0

    def test_idle_state_contradicts_awaiting_merge_stage(self, monkeypatch, tmp_path):
        """全部卡已合入（代码侧期望 idle）而 Jev 判 awaiting_merge_or_release，
        属于阶段判定与代码事实矛盾，必须 exit 4 而非静默放行。"""
        st = _state()
        st["_repo"] = tmp_path
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        body = json.dumps(_good_response()).encode("utf-8")
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(body))
        assert _run_main(monkeypatch, [], st) == 4
    def test_idle_state_allows_sync_suspicion(self, monkeypatch, tmp_path):
        """缺陷 22（C024）的端到端回归：全部卡已合入、Jev 对同步闭环猜疑，
        曾经会被 cross_check 升级成 exit 4——而这正是每次正常收口后的必经路径。
        必须 exit 0：真实未闭环由 sync_complete noul 门禁独立兜住。"""
        st = _state()
        st["_repo"] = tmp_path
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        r = _good_response()
        r["answers"]["current_stage"]["choice"] = "awaiting_bidirectional_sync"
        body = json.dumps(r).encode("utf-8")
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(body))
        assert _run_main(monkeypatch, [], st) == 0

    def test_low_confidence_exits_six(self, monkeypatch, tmp_path, capsys):
        """合规档位低于阈值但置信不足：不硬拦（exit 4），也不算通过，
        按 AGENTS.md『低置信需人工复核』收敛为 exit 6。"""
        st = _state(code_assertions=_empty_assertions(unmerged_cards=["C022"]))
        st["_repo"] = tmp_path
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        r = _good_response()
        r["answers"]["compliance"] = {"choice": "有关键环节缺失或存疑", "confidence": 0.31}
        body = json.dumps(r).encode("utf-8")
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(body))
        assert _run_main(monkeypatch, [], st) == 6
        out = capsys.readouterr().out
        assert "低置信判定" in out
        assert "退出码 6" in out

    def test_violation_beats_low_confidence(self, monkeypatch, tmp_path):
        """确定性违规与低置信并存时违规优先（exit 4）：红线 7 门禁不因
        语义判定不确定而被绕过。"""
        st = _state(code_assertions=_empty_assertions(
            unmerged_cards=["C022"], sediment_violations=["EN-0010"]))
        st["_repo"] = tmp_path
        monkeypatch.setenv("TYPESAFE_API_KEY", "k")
        r = _good_response()
        r["answers"]["compliance"] = {"choice": "有关键环节缺失或存疑", "confidence": 0.31}
        body = json.dumps(r).encode("utf-8")
        _patch_urlopen(monkeypatch, lambda *a, **k: _FakeResp(body))
        assert _run_main(monkeypatch, [], st) == 4


# ---------------------------------------------------------------------------
#  7. 常量与辅助函数的一致性
# ---------------------------------------------------------------------------

class TestConstants:
    def test_every_noul_question_has_a_label(self):
        for qid, q in jwc.QUESTIONS.items():
            if q["type"] == "noul":
                assert qid in jwc.NOUL_LABELS, qid
                assert qid in jwc.NOUL_QIDS, qid

    def test_polarity_keys_are_subset_of_labels(self):
        assert set(jwc.NOUL_POLARITY) <= set(jwc.NOUL_LABELS)

    def test_polarity_sides_are_valid(self):
        for qid, (side, phrase) in jwc.NOUL_POLARITY.items():
            assert side in ("low", "high"), qid
            assert phrase

    def test_pending_verification_has_no_polarity(self):
        """阶段判别量不是违规量，其矛盾由 cross_check 收口。"""
        assert "pending_verification" in jwc.NOUL_LABELS
        assert "pending_verification" not in jwc.NOUL_POLARITY

    def test_compliance_bands_are_ordered_and_unique(self):
        values = [v for _l, v, _r in jwc.COMPLIANCE_BANDS]
        assert values == sorted(values)
        assert len(set(values)) == len(values)
        assert jwc.COMPLIANCE_BAND_OF == {l: v for l, v, _r in jwc.COMPLIANCE_BANDS}

    def test_compliance_band_value_unknown_returns_none(self):
        assert jwc.compliance_band_value("不存在的档") is None
        assert jwc.compliance_band_value(None) is None

    def test_no_dead_compliance_labels(self):
        assert not hasattr(jwc, "COMPLIANCE_LABELS")

    @pytest.mark.parametrize("value,expected", [
        ("2c5955f", True),
        ("2c5955f0e1b7c4a9d3f6e8b1c5a7d9e0f1b3c5d7", True),
        ("2C5955F", False),          # 大写不算（git hash 小写）
        ("abc123", False),           # 短于 7 位
        ("abc1234 (squash)", False),
        ("待提交", False),
        ("", False),
        (None, False),
    ])
    def test_is_commit_hash(self, value, expected):
        assert jwc._is_commit_hash(value) is expected


# ---------------------------------------------------------------------------
#  7. gather_git：红线 2 的封存目录脏判定（真实 git 仓库）
# ---------------------------------------------------------------------------

class TestGatherGit:
    """frozen_dir_dirty 是唯一有流程依据的 git 信号，必须按真实 git 语义判。"""

    def _init_repo(self, tmp_path):
        for d in ("docs/devel/plan", "docs/devel/task"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
            (tmp_path / d / "T001.md").write_text("封存卡片\n", encoding="utf-8")
        # 从 env 里移除而不是置空：空 GIT_DIR 会让 git init 直接 128
        env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DIR", "GIT_WORK_TREE")}
        for args in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "初始封存"]):
            subprocess.run(["git"] + args, cwd=tmp_path, check=True,
                           capture_output=True, env=env)
        return env

    def test_clean_repo_is_not_dirty(self, tmp_path):
        env = self._init_repo(tmp_path)
        git = jwc.gather_git(tmp_path)
        assert git["frozen_dir_dirty"] is False
        assert "初始封存" in git["last_commit"]

    def test_modified_frozen_file_is_dirty(self, tmp_path):
        env = self._init_repo(tmp_path)
        (tmp_path / "docs/devel/task/T001.md").write_text("被改了\n", encoding="utf-8")
        assert jwc.gather_git(tmp_path)["frozen_dir_dirty"] is True

    def test_untracked_new_card_is_not_dirty(self, tmp_path):
        """Phase 2 立项允许在 plan/task 新建卡片，`??` 必须豁免。"""
        env = self._init_repo(tmp_path)
        (tmp_path / "docs/devel/plan/M002.md").write_text("新立项卡\n", encoding="utf-8")
        assert jwc.gather_git(tmp_path)["frozen_dir_dirty"] is False

    def test_non_frozen_dirty_file_is_ignored(self, tmp_path):
        """只盯 plan/task；改别处不算红线 2。"""
        env = self._init_repo(tmp_path)
        (tmp_path / "AGENTS.md").write_text("改红线描述\n", encoding="utf-8")
        assert jwc.gather_git(tmp_path)["frozen_dir_dirty"] is False

    def test_non_git_dir_degrades_gracefully(self, tmp_path):
        git = jwc.gather_git(tmp_path)
        assert git["frozen_dir_dirty"] is False
        assert git["last_commit"] == ""
