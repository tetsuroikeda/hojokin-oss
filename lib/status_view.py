"""開いたときに渡す情報（期限と作業、どの段階にも共通の決まり）と、今の状態の画面（SPEC F6・T6-1・共通の要件
「開いたときの情報量」、DESIGN 4.2・4.6・4.7 の3と5・5章。TASKS M3・K1・K2）。

開いたとき（SessionStart）に、hooks/status_hooks.py から session_start() を呼ぶ。
- 期限と作業（lib/deadlines.py）を、期限切れ・今日やること・近い締切・遅れている作業の順に、それぞれ締切順で書き、
  どの段階にも共通の決まりの短い文（lib/common_rules.py。1,200字まで）を添えて、Claude に渡す。
  続けて、外部への依頼と待ちの一覧（状態・だれがするか・目安の日数・始める日。済んだものも）を書く（K2）。
  期限ごとに、見込みか確定か（「確定」は社長に確かめた出来事の日付から出したもの）を示す（K1）。
  この2つは、ほかの処理が渡す情報の後ろに、見出し BRIEF_HEAD から始まる1つのまとまりとして置く（テストでも見分けるため）。
- 渡す情報の全体を10,000字以内にする（超えると先頭の2,000字しか渡らないため。SPEC 共通の要件）。期限の部分は
  DEADLINE_MAX 字まで、決まりの文は削らず、超える分はほかの処理の情報の後ろを切る（仮。B27 で T0-5 とともに見直す）。
- 今の状態の画面（会社のフォルダの直下の `今の状態.html`。DESIGN 4.5）を作り直す。案件が1つもなく、画面もまだない
  ときは作らない（仮）。外の部品（ライブラリや外のサイト）は読まない。今日の日付のほかに時刻を入れず、中身が同じなら
  書き直さない。書く先の途中とそのものに別名（シンボリックリンク）があれば書かない（lib/places.py）。
  画面は見るだけのものなので、会社のフォルダの .gitignore で版の履歴に入れない（lib/company_init.py。仮）。
- 期限を組み立てられないとき（今日の日付の差し替えが読めない など）も、決まりの文は必ず渡し、わけを添える。

標準のライブラリだけを使う。/usr/bin/python3（3.9）で動く。
"""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Dict, List, Optional

from lib import common_rules, dates, deadlines, place_text, places

BRIEF_HEAD = "## hojokin：開いたときの期限と作業"
MAX_CONTEXT = 10000  # SPEC 共通の要件「開いたときの情報量」
DEADLINE_MAX = 5000  # 期限と作業の部分の上限（仮）
GROUP_LIST_MAX = 10  # 1つの分け方に並べる数。超えた分は件数だけにして、画面に回す
PAGE_NAME = "今の状態.html"
TRIM_NOTE = "\n…（開いたときの情報が10,000字を超えるため、ここで切りました）"
CUT_NOTE = "\n…（長いため、ここで切りました。続きは 今の状態.html にあります）"
NONE_TEXT = "- ありません"
LATE_EMPTY = NONE_TEXT
STRONG_MARK = "【7日以内】"
REQUESTS_HEAD = "### 外部への依頼と待ち"
REQUEST_LIST_MAX = 12  # 依頼の一覧に並べる数


# ---- 開いたときに渡す文 ----


def _group_title(group: str, near_days: int) -> str:
    return f"{group}（{near_days}日以内）" if group == deadlines.NEAR else group


def task_facts(task: deadlines.Task) -> List[str]:
    """取り直しと依頼の作業に添える、始める日・目安の日数・だれがするか・状態の文。提出の作業は空。"""
    out = []
    if task.kind == deadlines.REQUEST:
        if task.start is not None:
            out.append(f"始める日（頼む日）：{task.start_label()}")
        if task.lead:
            out.append(f"目安：{task.lead}")
        out.append(f"だれ：{task.who}")
        out.append(f"状態：{task.state}")
    elif task.kind == deadlines.REACQUIRE:
        out.append(f"だれ：{task.who}" if task.who else "")
        if task.state:
            out.append(f"状態：{task.state}")
    return [x for x in out if x]


def request_line(task: deadlines.Task, today) -> str:
    """外部への依頼の一覧の1行（済んだものを含む）。"""
    d = task.due
    parts = [f"{task.doc}（{task.case}）", f"状態：{task.state}", task.who]
    if task.lead:
        parts.append(f"目安：{task.lead}")
    if task.start is not None:
        parts.append(f"始める日：{task.start_label()}")
    days = d.days_text(today) if not task.done else ""
    parts.append(f"締切：{d.label()}" + (f"（{days}）" if days else ""))
    line = "- " + "｜".join(parts)
    memo = [n for n in task.notes if not n.startswith("締切は")]
    if memo:
        line += "。" + "。".join(memo)
    return line


def task_line(task: deadlines.Task, today) -> str:
    d = task.due
    days = d.days_text(today)
    head = d.label() + (f"（{days}）" if days else "")
    if d.strong(today):
        head += STRONG_MARK
    parts = [head, task.case, task.what]
    line = "- " + "｜".join(parts)
    extra = task_facts(task) + list(task.notes)
    if d.dated and d.last < today:
        if task.remedies:
            extra.append("過ぎたときの手：" + "／".join(task.remedies))
        else:
            extra.append("過ぎたときの手が資料に見当たりません")
    if d.basis:  # 期限の台帳に残した出来事の日付から出した期限（lib/event_ledger.py。M10）
        extra.append("もとにした日：" + "、".join(d.basis))
    if d.sources:
        extra.append("出典：" + "、".join(d.sources))
    if extra:
        line += "。" + "。".join(extra)
    return line


def deadline_text(ov: deadlines.Overview) -> str:
    """期限と作業の部分（BRIEF_HEAD から）。"""
    today = ov.today
    when = dates.format_date(today) + ("（日付を差し替えています）" if ov.substituted else "")
    lines = [
        BRIEF_HEAD,
        "",
        f"今日：{when}。日時は日本時間。近い締切は{ov.near_days}日以内で、{deadlines.STRONG_DAYS}日以内には{STRONG_MARK}を付けています。",
        "最初の返事で、下の「期限切れ」「今日やること」「近い締切」「遅れている作業」を、この順に、締切順のまま社長に示してください。"
        "期限切れには、添えた「過ぎたときの手」を出典つきで示し、資料に手が見当たらなければ、事務局への問い合わせ文の案を作ってください。"
        "日付と日数は、この一覧の値を使ってください（頭で計算し直さない）。「見込み」は予定の日付から出したもので、まだ決まっていません。"
        "「確定」は、社長に確かめた出来事の日付から出したものです。",
    ]
    if not ov.cases and not ov.problems:
        lines += ["", "案件はまだありません（期限はありません）。"]
    for group in deadlines.GROUPS:
        items = ov.groups.get(group) or []
        lines += ["", f"### {_group_title(group, ov.near_days)}"]
        if not items:
            lines.append(LATE_EMPTY if group == deadlines.LATE else NONE_TEXT)
            continue
        lines += [task_line(t, today) for t in items[:GROUP_LIST_MAX]]
        if len(items) > GROUP_LIST_MAX:
            lines.append(f"- ほか {len(items) - GROUP_LIST_MAX}件（今の状態.html にあります）")
    requests = ov.requests()
    if requests:
        lines += ["", REQUESTS_HEAD]
        lines += [request_line(t, today) for t in requests[:REQUEST_LIST_MAX]]
        if len(requests) > REQUEST_LIST_MAX:
            lines.append(f"- ほか {len(requests) - REQUEST_LIST_MAX}件（今の状態.html にあります）")
        asking = [t.doc for t in requests if not t.lead and not t.done]
        if asking:
            lines.append(f"目安の日数をまだ聞いていない依頼：{'、'.join(asking)}（社長に聞いて、junbi の期限の道具で残します）。")
    broken = [c for c in ov.cases if c.problem]
    if broken or ov.problems:
        lines += ["", "### 組み立てられなかったもの"]
        lines += [f"- {c.name}：{c.problem}" for c in broken]
        lines += [f"- {p}" for p in ov.problems]
    notes = [f"- {c.name}：{n}" for c in ov.cases for n in c.notes]
    if notes:
        lines += ["", "### 書類について"] + notes
    if ov.later or ov.undated:
        lines += ["", f"そのほかに、{ov.near_days}日より先の期限が{len(ov.later)}件、日付がまだ出せない期限が"
                      f"{len(ov.undated)}件あります（一覧は 今の状態.html）。"]
    if ov.done:
        lines.append(f"済んだもの（届いた依頼、取る期間の内の原本がある書類）が{len(ov.done)}件あります（今の状態.html）。")
    if ov.cases:
        lines.append(f"今の状態の画面：会社のフォルダの直下の {PAGE_NAME}（見るだけ。開くたびに作り直します）。")
    text = "\n".join(lines)
    if len(text) > DEADLINE_MAX:
        cut = text.rfind("\n", 0, DEADLINE_MAX - len(CUT_NOTE))
        text = text[: cut if cut > 0 else DEADLINE_MAX - len(CUT_NOTE)] + CUT_NOTE
    return text


def failure_text(error: Exception) -> str:
    """期限を組み立てられなかったときの、BRIEF_HEAD からの文。"""
    return "\n".join([
        BRIEF_HEAD,
        "",
        f"期限と作業を組み立てられませんでした（{type(error).__name__}: {error}）。"
        "期限を社長に示すときは、junbi の道具で制度データの期限を確かめてください。",
    ])


def brief(ov_text: str) -> str:
    """期限と作業の部分に、どの段階にも共通の決まりの文を添える。"""
    return f"{ov_text}\n\n{common_rules.TEXT.rstrip()}"


def without_brief(text: str) -> str:
    """渡す情報から、このまとまり（BRIEF_HEAD から後ろ）を除いたもの（テストで、ほかの処理の情報を見るため）。"""
    index = text.find(BRIEF_HEAD)
    return text if index < 0 else text[:index].rstrip("\n")


def combine(current: Optional[str], block: str) -> str:
    """ほかの処理が渡す情報の後ろに、このまとまりを置く。全体が10,000字を超えるなら、ほかの処理の情報の後ろを切る。"""
    if not current:
        return block[:MAX_CONTEXT]
    room = MAX_CONTEXT - len(block) - 1
    if len(current) > room:
        keep = max(0, room - len(TRIM_NOTE))
        current = current[:keep].rstrip() + TRIM_NOTE
    return f"{current}\n{block}"


# ---- 今の状態の画面 ----

STYLE = """
body{font-family:-apple-system,"Hiragino Sans","Yu Gothic",sans-serif;margin:24px;color:#1f2328;background:#fff;line-height:1.6}
h1{font-size:1.6em;margin:0 0 4px}
h2{font-size:1.25em;border-bottom:2px solid #d0d7de;padding-bottom:4px;margin-top:32px}
h3{font-size:1.05em;margin-top:24px}
table{border-collapse:collapse;width:100%;margin:8px 0 16px}
th,td{border:1px solid #d0d7de;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f6f8fa;white-space:nowrap}
.note{color:#57606a;font-size:.92em}
.overdue td{background:#ffebe9}
.strong td{background:#fff8c5}
.mark{font-weight:bold;color:#cf222e}
.now{font-weight:bold}
.done{color:#57606a}
ol.flow li{margin:2px 0}
"""


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _task_rows(tasks: List[deadlines.Task], today, overdue: bool = False) -> List[str]:
    rows = []
    for t in tasks:
        d = t.due
        cls = "overdue" if overdue else ("strong" if d.strong(today) else "")
        mark = f' <span class="mark">{_e(STRONG_MARK)}</span>' if d.strong(today) and not overdue else ""
        memo = []
        if t.start is not None:
            memo.append(f"始める日（頼む日）：{t.start_label()}")
        if t.lead:
            memo.append(f"目安：{t.lead}")
        memo += list(t.notes)
        if d.basis:
            memo.append("もとにした日：" + "、".join(d.basis))
        if overdue:
            memo.append("過ぎたときの手：" + "／".join(t.remedies) if t.remedies else "過ぎたときの手が資料に見当たりません")
        state = t.state if t.state else "—"
        rows.append(
            f'<tr class="{cls}"><td>{_e(d.label())}{mark}</td><td>{_e(d.days_text(today))}</td>'
            f"<td>{_e(t.case)}</td><td>{_e(t.what)}</td><td>{_e(d.state_word)}</td>"
            f"<td>{_e(t.who or '—')}</td><td>{_e(state)}</td>"
            f"<td>{_e('、'.join(d.sources))}</td><td>{_e('。'.join(memo))}</td></tr>")
    return rows


TASK_HEAD = ("<tr><th>締切</th><th>あと何日</th><th>案件</th><th>期限の名前</th><th>見込みか確定か</th>"
             "<th>だれがするか</th><th>依頼の状態</th><th>出典</th><th>メモ</th></tr>")


def _task_table(tasks: List[deadlines.Task], today, empty: str, overdue: bool = False) -> List[str]:
    if not tasks:
        return [f'<p class="note">{_e(empty)}</p>']
    return ["<table>", TASK_HEAD] + _task_rows(tasks, today, overdue) + ["</table>"]


def render_page(ov: deadlines.Overview, company_name: str) -> str:
    """今の状態.html の中身（最小限。B27 で、工程表・書類ごとの状態・不備・申請書の進み具合などを足す）。"""
    today = ov.today
    when = dates.format_date(today) + ("（日付を差し替えています）" if ov.substituted else "")
    out = [
        "<!doctype html>",
        '<html lang="ja"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>今の状態｜{_e(company_name)}</title>",
        f"<style>{STYLE}</style></head><body>",
        "<h1>今の状態</h1>",
        f'<p class="note">{_e(company_name)}｜{_e(when)}時点（日本時間）。この画面は見るだけです。'
        "Claude を開くたびに作り直すので、ここに書き込んでも残りません。済んだことは、Claude に伝えてください。</p>",
        "<h2>期限と作業</h2>",
        f'<p class="note">近い締切は{ov.near_days}日以内。{deadlines.STRONG_DAYS}日以内は色を付けています。'
        "「見込み」は、予定の日付から出した期限です。</p>",
    ]
    for group in deadlines.GROUPS:
        items = ov.groups.get(group) or []
        out.append(f"<h3>{_e(_group_title(group, ov.near_days))}</h3>")
        out += _task_table(items, today, "ありません", overdue=group == deadlines.OVERDUE)
    out.append(f"<h3>{_e(f'{ov.near_days}日より先の期限')}</h3>")
    out += _task_table(ov.later, today, "ありません")
    out.append("<h3>日付がまだ出せない期限</h3>")
    if ov.undated:
        out += ["<table>", "<tr><th>案件</th><th>期限の名前</th><th>決め方</th><th>メモ</th></tr>"]
        out += [f"<tr><td>{_e(t.case)}</td><td>{_e(t.what)}</td><td>{_e(t.due.label())}</td>"
                f"<td>{_e('。'.join(t.notes))}</td></tr>" for t in ov.undated]
        out.append("</table>")
    else:
        out.append('<p class="note">ありません</p>')
    out.append("<h3>済んだもの</h3>")
    out += _task_table(ov.done, today, "ありません")

    out.append("<h2>外部への依頼と待ち</h2>")
    requests = ov.requests()
    if requests:
        out += ["<table>", "<tr><th>書類</th><th>案件</th><th>依頼の状態</th><th>だれがするか</th><th>目安の日数</th>"
                "<th>始める日</th><th>締切</th><th>見込みか確定か</th><th>メモ</th></tr>"]
        for t in requests:
            memo = [n for n in t.notes if not n.startswith("締切は")]
            out.append(f"<tr><td>{_e(t.doc)}</td><td>{_e(t.case)}</td><td>{_e(t.state)}</td><td>{_e(t.who)}</td>"
                       f"<td>{_e(t.lead or 'まだ聞いていません')}</td><td>{_e(t.start_label() or '—')}</td>"
                       f"<td>{_e(t.due.label())}</td><td>{_e(t.due.state_word)}</td><td>{_e('。'.join(memo))}</td></tr>")
        out.append("</table>")
    else:
        out.append('<p class="note">ありません。人に頼む書類（見積書、金融機関の確認書など）は、頼んだときに Claude に伝えてください。</p>')

    out.append("<h2>案件</h2>")
    if not ov.cases:
        out.append('<p class="note">案件はまだありません。</p>')
    for case in ov.cases:
        out.append(f"<h3>{_e(case.name)}</h3>")
        if case.title:
            out.append(f'<p class="note">{_e(case.title)}</p>')
        if case.problem:
            out.append(f"<p>{_e(case.problem)}</p>")
            continue
        state = "（提出済み）" if case.submitted else ""
        nxt = case.next_task()
        line = f"今の段階：{case.current}{state}"
        if nxt is not None:
            days = nxt.due.days_text(today)
            line += f"。次の締切：{nxt.what}　{nxt.due.label()}" + (f"（{days}）" if days else "")
        out.append(f"<p>{_e(line)}</p>")
        out.append('<ol class="flow">')
        for row in case.stages:
            cls = "now" if row.state == "今" else ("done" if row.state == "済み" else "")
            due = f"：{row.due.label()}" if row.due is not None else ""
            cond = "（必要なときだけ）" if row.conditional else ""
            out.append(f'<li class="{cls}">{_e(f"［{row.state}］{row.name}{cond}{due}")}</li>')
        out.append("</ol>")
        if case.documents:
            out.append(f'<p class="note">{_e(f"今の段階（{case.current}）の必須の書類")}</p>')
            out += ["<table>", "<tr><th>書類</th><th>発行元</th><th>分け方</th><th>状態</th></tr>"]
            out += [f"<tr><td>{_e(d.name)}</td><td>{_e(d.issuer)}</td><td>{_e(d.kind)}</td><td>{_e(d.state)}</td></tr>"
                    for d in case.documents]
            out.append("</table>")
            out.append('<p class="note">「台帳にあり」は、書類の台帳に同じ種類の原本があるということです。'
                       "期数・有効期限・中身は、書類の確かめ（shorui）で見ます。</p>")
        for note in case.notes:
            out.append(f'<p class="note">{_e(note)}</p>')
    if ov.problems:
        out.append("<h2>組み立てられなかったもの</h2><ul>")
        out += [f"<li>{_e(p)}</li>" for p in ov.problems]
        out.append("</ul>")
    out.append("</body></html>")
    return "\n".join(out) + "\n"


def write_page(folder: Path, page: str) -> Optional[str]:
    """今の状態.html を書く。中身が同じなら書き直さない。書けなかったときは、そのわけ（書けたら None）。"""
    folder = Path(folder)
    problem = place_text.write_problem(folder, PAGE_NAME, f"{PAGE_NAME} を作り直していません")
    if problem:
        return problem
    path = places.actual(folder, PAGE_NAME, partial=True)
    data = page.encode("utf-8")
    tmp = None
    try:
        if os.path.lexists(str(path)):
            if not path.is_file():
                return f"{PAGE_NAME} がファイルでないため、作り直していません"
            if path.read_bytes() == data:
                return None
        # 「~*.tmp」は会社のフォルダの .gitignore にあるので、書きかけが版に残らない
        tmp = path.with_name(f"~{PAGE_NAME}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(str(tmp), str(path))
        tmp = None
    except OSError as error:
        return f"{PAGE_NAME} を書けませんでした（{error}）"
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
    return None


def page_wanted(folder: Path, ov: deadlines.Overview) -> bool:
    """画面を作るか。案件が1つもなく、画面もまだないときは作らない（仮）。"""
    return bool(ov.cases) or os.path.lexists(str(Path(folder) / PAGE_NAME))


# ---- 開いたとき ----


def session_start(folder: Path, output: Optional[dict]) -> dict:
    """開いたときの出力（additionalContext）の後ろに、期限と作業・共通の決まりを置き、今の状態の画面を作り直す。"""
    folder = Path(folder)
    try:
        ov = deadlines.build(folder)
    except Exception as error:  # 今日の日付の差し替えが読めない など。決まりの文は必ず渡す
        text = failure_text(error)
    else:
        text = deadline_text(ov)
        if page_wanted(folder, ov):
            try:
                problem = write_page(folder, render_page(ov, deadlines.nfc(folder.name)))
            except Exception as error:
                problem = f"{PAGE_NAME} を作れませんでした（{type(error).__name__}: {error}）"
            if problem:
                text += f"\n{problem}"
    result = dict(output or {})
    hso = dict(result.get("hookSpecificOutput") or {"hookEventName": "SessionStart"})
    current = hso.get("additionalContext")
    hso["additionalContext"] = combine(current if isinstance(current, str) else "", brief(text))
    result["hookSpecificOutput"] = hso
    return result
