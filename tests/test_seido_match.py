"""件名が違う同じ件の突き合わせ（11/6 のリハーサルの直し。SPEC F3・F7、DESIGN 9.2）。

11/6 のリハーサルで出たこと
- seido_data --merge：2回目の読み取りの件名が1回目と少し違うと、同じ件でも「2回目の読み取りに、この件がありません」になった。
  2回目が読んでいないページ（交付申請・実績報告の手引き）の件も、同じ言い方で要確認になった。
- kaitei --diff：前の回と今の回で件名が違うと、中身が同じ件まで「消えた」と「足した」に分かれ、783件の差になった。

確かめること
- 件名の形（全角・空白・かっこ）がそろえば同じ件。そろわなければ、件名と中身の近さで組にし、組にしたことを結果に出す。
- 件名の中の数が食い違う件（従業員数5人以下と6～20人、基本要件①と②）は組にしない。
- 同じ件名の件が2つあっても、1つにつぶさない。
- 1回目にあって2回目にない件は要確認のまま。ただし、2回目の読んだページが出典のページを含まないときは比べず、別に並べる。
- 改訂の差では、件名が変わっただけの件は差に出さず、件ごと足した・消えた件は1件にまとめ、言い回しだけの違いは分けて出す。

テストの値は、テストのためだけに作った架空のもの。
"""

from __future__ import annotations

import copy

from lib import kaitei, seido_data, urakadori

DOC = "要領T"
GUIDE = "手引きT"


def sv(value, page, sentence, doc=DOC, state="確認済み") -> dict:
    return {"値": value, "出典": [{"資料": doc, "ページ": page}], "根拠の文": sentence, "状態": state}


def first_reading() -> dict:
    return {
        "読み取り": {"章": "４．申請の手続き", "回目": 1,
                   "読んだページ": [{"資料": DOC, "ページ": 2, "終わりのページ": 5}, {"資料": GUIDE, "ページ": 10}]},
        "制度データ": {
            "決まった期日": [{"名前": "公募締切日", "日時": sv({"日時": "2027-03-12T16:00+09:00"}, 2, "締切：2027年3月12日16:00")}],
            "補助額": [
                {"区分": "中小企業（従業員数5人以下）", "上限": sv(5000000, 3, "5人以下 500万円"),
                 "補助率": sv("1/2", 3, "補助率 1/2"),
                 "特例": [{"名前": "大幅賃上げに係る補助上限額引き上げの特例", "種類": "上限の置き換え",
                          "値": sv(7000000, 3, "特例 700万円")}]},
                {"区分": "中小企業（従業員数6～20人）", "上限": sv(10000000, 3, "6～20人 1,000万円"),
                 "補助率": sv("1/2", 3, "補助率 1/2")},
            ],
            "数値の要件": [
                {"名前": "給与の伸び", "基準": sv("年平均3.5%以上", 4, "給与を年平均3.5%以上伸ばす")},
                {"名前": "給与の伸び", "基準": sv("年平均6.0%以上", 4, "特例は給与を年平均6.0%以上伸ばす")},
            ],
            "書類": [
                {"名前": "損益計算書", "区分": "必須", "手続き": ["申請"], "内容": sv("損益計算書", 5, "損益計算書 2期分")},
                {"名前": "登記簿の写し", "区分": "必須", "手続き": ["申請"], "内容": sv("登記簿の写し", 5, "登記簿の写し")},
                {"名前": "見積書", "区分": "必須", "手続き": ["交付申請"], "内容": sv("見積書", 10, "見積書を出す", doc=GUIDE)},
            ],
        },
    }


def second_reading() -> dict:
    """1回目と同じ中身を、件名だけ言い換えて読んだ2回目（手引きのページは読んでいない）。"""
    second = copy.deepcopy(first_reading())
    second["読み取り"]["回目"] = 2
    second["読み取り"]["章"] = "4.申請の手続き"   # 章の名前の全角・半角の違いも同じ章
    second["読み取り"]["読んだページ"] = [{"資料": DOC, "ページ": 2, "終わりのページ": 5}]
    part = second["制度データ"]
    part["決まった期日"][0]["名前"] = "締切"
    part["補助額"][0]["区分"] = "中小企業者（従業員5人以下）"
    part["補助額"][0]["特例"][0]["名前"] = "大幅賃上げ特例（補助上限額の引き上げ）"
    part["補助額"][1]["区分"] = "中小企業者（従業員6〜20人）"
    part["書類"][0]["名前"] = "損益計算書（直近2期分）"
    part["書類"] = part["書類"][:2]   # 手引きの「見積書」は、2回目が読んでいないページの件
    return second


def merge(first: dict, second: dict):
    """まとめる道具と同じく、1回目をまとめた制度データに2回目を突き合わせる（その場で直す）。"""
    full = copy.deepcopy(first["制度データ"])
    result = seido_data.MergeResult()
    seido_data.compare_readings(full, [first], [second], result)
    return full, result


def states(node) -> list:
    out = []
    if isinstance(node, dict) and "値" in node and "状態" in node:
        return [node["状態"]]
    if isinstance(node, dict):
        for v in node.values():
            out += states(v)
    elif isinstance(node, list):
        for v in node:
            out += states(v)
    return out


# ---- 2回の読み取りの突き合わせ（seido_data --merge） ----


def test_renamed_entries_are_matched_and_reported() -> None:
    full, result = merge(first_reading(), second_reading())
    # 件名を言い換えただけの件は、食い違いにも「この件がありません」にもならない
    assert result.double_diffs == []
    assert set(states(full)) == {"確認済み"}
    near = {(top, a, b) for _ch, top, a, b, _how in result.near_pairs}
    assert ("決まった期日", "公募締切日", "締切") in near
    assert ("補助額", "中小企業（従業員数5人以下）", "中小企業者（従業員5人以下）") in near
    assert ("補助額", "中小企業（従業員数6～20人）", "中小企業者（従業員6〜20人）") in near
    assert ("書類", "損益計算書", "損益計算書（直近2期分）") in near
    assert any(a == "大幅賃上げに係る補助上限額引き上げの特例" for _c, _t, a, _b, _h in result.near_pairs)
    assert all(how.startswith("件名 ") for *_x, how in result.near_pairs)  # 近さを結果に出す
    assert result.second_only == []
    # 手引きの見積書は、2回目が読んでいないページの件として並べ、要確認にしない
    assert [(where, pages) for _ch, where, pages in result.second_unread] == [("書類「見積書」", "手引きT p.10")]


def test_renamed_entry_with_a_different_number_is_still_a_difference() -> None:
    second = second_reading()
    second["制度データ"]["補助額"][0]["上限"]["値"] = 6000000
    full, result = merge(first_reading(), second)
    assert full["補助額"][0]["上限"]["状態"] == "要確認"
    assert "2回の読み取り：1回目は 5000000、2回目は 6000000" in full["補助額"][0]["上限"]["注記"]
    assert [w for w, _why in result.double_diffs] == ["補助額「中小企業（従業員数5人以下）」の上限"]


def test_names_with_different_numbers_are_never_paired() -> None:
    second = second_reading()
    # 2回目が「5人以下」を落とし、「6～20人」だけを読んだ：5人以下を6～20人と組にしない
    del second["制度データ"]["補助額"][0]
    full, result = merge(first_reading(), second)
    assert not any(a.startswith("中小企業（従業員数5人以下）") and "6" in b for _c, _t, a, b, _h in result.near_pairs)
    assert full["補助額"][0]["上限"]["状態"] == "要確認"
    assert "2回目の読み取りに、この件がありません" in full["補助額"][0]["上限"]["注記"]
    assert full["補助額"][1]["上限"]["状態"] == "確認済み"
    assert seido_data.name_closeness("基本要件①", "基本要件②") == 0.0
    assert seido_data.name_closeness("従業員数5人以下", "従業員数6～20人") == 0.0
    assert seido_data.name_closeness("②給与（5年目計画）", "⑤給与（2年目計画）") == 0.0


def test_entry_missing_on_read_pages_is_still_check() -> None:
    second = second_reading()
    del second["制度データ"]["書類"][1]  # 2回目が読んだページ（p.5）にある「登記簿の写し」を落とした
    full, result = merge(first_reading(), second)
    assert full["書類"][1]["内容"]["状態"] == "要確認"
    assert ("書類「登記簿の写し」の内容", "2回目の読み取りに、この件がありません") in result.double_diffs
    assert [where for _ch, where, _p in result.second_unread] == ["書類「見積書」"]


def test_entry_on_pages_the_second_did_read_is_compared() -> None:
    second = second_reading()
    second["読み取り"]["読んだページ"].append({"資料": GUIDE, "ページ": 9, "終わりのページ": 11})
    full, result = merge(first_reading(), second)
    # 手引きの p.10 を2回目が読んだのに見積書がない：要確認
    assert full["書類"][2]["内容"]["状態"] == "要確認"
    assert result.second_unread == []


def test_same_named_entries_are_not_collapsed() -> None:
    second = second_reading()
    second["制度データ"]["数値の要件"][1]["基準"]["値"] = "年平均6.5%以上"
    full, result = merge(first_reading(), second)
    # 同じ名前の2件を別の件として比べる（名前で1つにまとめると、1件目が比べられない・違う件と比べる）
    assert full["数値の要件"][0]["基準"]["状態"] == "確認済み"
    assert full["数値の要件"][1]["基準"]["状態"] == "要確認"
    assert len([w for w, _y in result.double_diffs if w.startswith("数値の要件")]) == 1


def test_document_kind_disagreement_is_check() -> None:
    second = second_reading()
    second["制度データ"]["書類"][1]["区分"] = "条件付き"
    full, result = merge(first_reading(), second)
    assert full["書類"][1]["内容"]["状態"] == "要確認"
    assert ("書類「登記簿の写し」の内容", "1回目は「必須」、2回目は「条件付き」") in result.double_diffs


def test_merge_report_shows_near_pairs_and_unread_pages() -> None:
    _full, result = merge(first_reading(), second_reading())
    verified = urakadori.Result()
    out = seido_data.merge_report("案件", result, verified, "記録/制度データ/x.json")
    assert "件名が1回目と違い、件名と中身の近さで同じ件として比べた件：" in out
    assert "| 4.申請の手続き | 決まった期日 | 公募締切日 | 締切 | 件名 " in out
    assert "2回目の読み取りが出典のページを読んでいないので、比べていない件：1" in out
    assert "4.申請の手続き：書類「見積書」（出典 手引きT p.10）" in out


def test_pair_items_prefers_exact_names_and_one_to_one() -> None:
    olds = [("技術導入費の上限", "技術導入費は500万円まで"), ("外注費の上限", "外注費は300万円まで")]
    news = [("外注費の上限", "外注費は300万円まで"), ("技術導入費の上限額", "技術導入費は500万円まで")]
    pairs = seido_data.pair_items(olds, news)
    assert [(p.old, p.new, p.near) for p in pairs] == [(0, 1, True), (1, 0, False)]
    # 件名も中身も遠い件は、組にしない
    assert seido_data.pair_items([("中古品", "中古品の購入費")], [("収入印紙", "収入印紙の代金")]) == []


# ---- 改訂の差（kaitei --diff） ----


def full_data(reading: dict) -> dict:
    data = copy.deepcopy(reading["制度データ"])
    data["資料"] = []
    return data


def test_diff_does_not_split_renamed_entries() -> None:
    old = full_data(first_reading())
    new = full_data(second_reading())
    renames = []
    changes = kaitei.diff_data(old, new, {}, renames)
    # 件名が変わっただけの件は、差に出ない（前は、件の値がどれも「消えた」と「足した」に分かれた）
    assert [c.kind for c in changes if c.kind in ("消えた", "足した") and not c.entry] == []
    assert {(r.old, r.new) for r in renames} >= {
        ("決まった期日「公募締切日」", "決まった期日「締切」"),
        ("補助額「中小企業（従業員数5人以下）」", "補助額「中小企業者（従業員5人以下）」")}
    # 2回目にない見積書は、件ごと消えた1件
    gone = [c for c in changes if c.kind == "消えた"]
    assert [(c.entry, c.where) for c in gone] == [("書類「見積書」", "書類「見積書」の内容")]


def test_diff_value_change_in_renamed_entry() -> None:
    old = full_data(first_reading())
    new = full_data(second_reading())
    new["決まった期日"][0]["日時"]["値"] = {"日時": "2027-04-09T16:00+09:00"}
    changes = kaitei.diff_data(old, new, {})
    changed = [c for c in changes if c.kind == "値が変わった"]
    assert [c.where for c in changed] == ["決まった期日「締切」の日時"]


def test_diff_groups_whole_entries_and_same_changes() -> None:
    old = full_data(first_reading())
    new = copy.deepcopy(old)
    new["補助額"].append({"区分": "再生事業者（従業員数5人以下）", "上限": sv(5000000, 3, "5人以下 500万円"),
                        "補助率": sv("2/3", 3, "再生事業者 2/3")})
    for a in new["補助額"][:2]:
        a["補助率"]["値"] = "2/3"
        a["補助率"]["根拠の文"] = "補助率 2/3"
    r = kaitei.DiffResult("前", "後", "第1回", "第2回", [], kaitei.diff_data(old, new, {}), [])
    kinds = [(k, len(cs), len(others)) for k, cs, others, _ok in r.grouped()]
    # 足した件は件ごとに1件（中の2つの値をまとめる）。区分ごとの同じ変化（補助率 1/2 → 2/3）は1件にまとめる
    assert ("件ごと足した", 2, 0) in kinds
    assert ("値が変わった", 1, 1) in kinds
    assert len(kinds) == 2
    text = kaitei.diff_report(r)
    assert "変わった項目：2件" in text and "同じ変化がほかに 1か所" in text


def test_diff_separates_wording_only_changes() -> None:
    old = full_data(first_reading())
    new = copy.deepcopy(old)
    new["数値の要件"][0]["基準"]["値"] = "毎年、平均で3.5%以上にする"
    new["書類"][1]["内容"]["値"] = "登記事項証明書"
    changes = kaitei.diff_data(old, new, {})
    kinds = {c.where: c.kind for c in changes}
    assert kinds["数値の要件「給与の伸び」の基準"] == kaitei.WORDING      # 数は同じで言い回しだけ
    assert kinds["書類「登記簿の写し」の内容"] == kaitei.WORDING
    new["数値の要件"][0]["基準"]["値"] = "年平均4.0%以上"
    changes = kaitei.diff_data(old, new, {})
    assert {c.where: c.kind for c in changes}["数値の要件「給与の伸び」の基準"] == "値が変わった"
    # 決まった言葉を選ぶ欄（何の上限 など）が変われば、言い回しではない
    assert not kaitei.only_wording({"何の上限": "補助金額", "金額": 1}, {"何の上限": "補助対象経費", "金額": 1})


# ---- 裏取り（urakadori）：丸数字と資料の呼び名 ----


def test_circled_numbers_are_read_as_numbers() -> None:
    assert urakadori.normalize("❶ 宣誓 ❷ 基本情報 ⓫ 認証 ⓬ 確認") == "1宣誓2基本情報11認証12確認"
    assert urakadori.normalize("① ⑫ ㉑") == urakadori.normalize("1 12 21").replace(" ", "")
    assert urakadori.normalize("⓵ ➀ ➊ ⓿") == "1110"
    evidence = "|".join(urakadori.numeric_fragments("応募申請手続きは①～⑫まであります。…❶ 宣誓・手引き ❷ 基本情報 ⓫ メールアドレス認証 ⓬ 確認"))
    flow = [{"順番": 1, "名前": "宣誓・手引き"}, {"順番": 2, "名前": "基本情報"},
            {"順番": 11, "名前": "メールアドレス認証"}, {"順番": 12, "名前": "確認"}]
    assert urakadori.value_problems(flow, evidence) == []
    assert urakadori.value_problems([{"順番": 3, "名前": "基本情報"}], evidence) == ["1つ目：数「3」が根拠の文にありません"]


def test_original_file_is_checked_against_doc_ids() -> None:
    docs = {"Wordその1・2": "事業計画書 その1・その2（参考様式）", "要領9": "公募要領"}
    evidence = "|".join(urakadori.numeric_fragments("申請にあたっては電子申請システムに PDF 形式のファイル等を添付してください。"))
    good = {"種類": "ファイル", "提出の形式": "PDF", "元のファイル": "Wordその1・2"}
    assert urakadori.value_problems(good, evidence, docs=docs) == []
    unknown = dict(good, 元のファイル="Word様式")
    assert urakadori.value_problems(unknown, evidence, docs=docs) == [
        "「Word様式」が、資料の一覧の id にありません（資料の id：Wordその1・2・要領9）"]
    by_name = dict(good, 元のファイル="事業計画書その1・その2（参考様式）")
    assert "資料の一覧の id（「Wordその1・2」）を書いてください" in urakadori.value_problems(by_name, evidence, docs=docs)[0]
    # 文字の値の中の資料の呼び名は、根拠の文の言葉・数と照らさない
    assert urakadori.value_problems("Wordその1・2 の様式で PDF 形式のファイル等を添付", evidence, docs=docs) == []
    assert urakadori.value_problems("Wordその1・2 の様式で PDF 形式のファイル等を添付", evidence) != []
