"""画面入力の守り（DESIGN 5章「提出ボタンを押さない」「確認・誓約・同意のチェック欄に入れない」
「添付するのは、決まった写しだけ」「パスワードを扱わない」「画面入力は、担当者が呼んだときだけ」）。

hooks から次の3つを呼ぶ。どれも会社のフォルダ（目印のあるフォルダ）でだけ呼ばれる。
- user_prompt_submit：担当者が `/hojokin:nyuryoku` を呼んだら、そのセッションの「画面入力の許可」を残す。
- post_tool_use：ページを読んだ結果（read_page）から、部品の番号と種類・名前・囲むラベルの対応を控える。
- pre_tool_use：通してよいものだけを通し、それ以外（知らない道具の名前を含む）は拒む。

対象は、名前に Claude_Browser・claude-in-chrome・computer-use を含む道具。
- computer-use（画面を操作する機能）は、会社のフォルダではすべて拒む。
- ページを読むだけの道具（read_page・find・画面の写しなど）と、タブの切り替え、ページの移動は、許可がなくても通す。
  ページの移動とタブの切り替えでは、部品の控えを捨てる（番号が画面ごとに振り直されるため。実験 E1）。
  ページの移動は、http・https で始まる URL と back・forward だけを通す（javascript: などは拒む）。
- 控えは、読んだタブと同じタブと分かる操作にだけ使う。tabId を付けて読んだ控えは、同じ tabId を
  付けた操作だけ。tabId を省いて読んだ控えは、tabId を省いた操作か、結果の「Executed on tabId」と
  同じ tabId を付けた操作だけ。
- クリック・入力・添付は、許可がなければ拒む。許可があっても、次のものだけを通す。
  - クリック：番号で指し、控えで「押してよいボタン」（制度データの画面の定義の和）に当たるボタン・リンク。
    名前に押さないボタンの語（PROHIBITED_BUTTON_WORDS）を含むものは、制度データにかかわらず拒む。
    チェック欄・ラジオボタン・選択欄と、そのラベルへのクリックは、下の「選ぶ欄」の決まりで見る。
    クリックを通したら、控えを捨てる（次の操作の前に、ページを読み直させる）。
  - 入力（form_input）：文字の欄（パスワード・隠れた欄・添付の欄を除く）と、下の「選ぶ欄」。
  - 選ぶ欄（チェック欄・ラジオボタン・選択欄）：囲むラベルから名前が読め、名前に
    PROHIBITED_FIELD_WORDS（確認・誓約・同意・宣誓）を含まず、制度データの申請画面で
    ツールが入れる欄（担当者が入れる＝false）に、種類も合わせて当たるもの。
    名前の照らし方：画面の名前が欄の名前と同じか、画面の名前の「：」より前が欄の名前と同じか
    （模擬画面の「項目名：説明」の形と、ラジオボタンの「問い：値」の形。NFC・空白をそろえて比べる）。
  - 添付（file_upload）：控えで添付の欄に当たる部品に、会社のフォルダの
    `案件/<案件>/<段階>/添付する書類/`（効果報告の `<段階>/1年目/添付する書類/` も）の中にあるファイルだけ。
  - まとめて動かす道具（browser_batch）：中を1つずつ同じ決まりで見る。ページが変わる動作
    （クリック・移動・タブの切り替え）は1回までで、最後に限る。中にまとめて動かす道具は入れない。
- 座標でのクリック、ダブルクリック・右クリック・ドラッグ、打ち込み、Enter などのキー、
  JavaScript とショートカットの実行は拒む。

許可と控えは `.hojokin/一時/画面入力/<セッション>/` に置く（版の履歴に入れない。DESIGN 4.5）。
許可はそのセッションの間だけ有効（セッションの ID ごとに分ける）。
Python 3.9 の標準のライブラリだけで動く形にする。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from lib import company, places
from lib.page_tree import CHOICE_ROLES, TEXT_ROLES, Page, normalize, parse, response_text

# 押さないボタンの語。制度データ（AI が下書きする）にかかわらず、名前に含むボタン・リンクは押させない
PROHIBITED_BUTTON_WORDS = ("提出", "送信", "申請する", "確定", "完了")
# ツールが入れない欄の語。名前に含むチェック欄・ラジオボタン・選択欄には入れない（担当者が入れる）
PROHIBITED_FIELD_WORDS = ("確認", "誓約", "同意", "宣誓")

NYURYOKU_COMMAND = "/hojokin:nyuryoku"
STATE_DIR = "画面入力"
PERMISSION_FILE = "許可.json"
SNAPSHOT_FILE = "控え.json"
SCHEME_DIR = ("記録", "制度データ")
CASE_DIR = "案件"
ATTACH_DIR = "添付する書類"

# ブラウザの種類（部品の番号は、ブラウザごとに別に振られる）
BUILTIN = "内蔵ブラウザ"
CHROME = "Claude in Chrome"
COMPUTER_USE = "computer-use"
UNKNOWN = "知らない道具"

# ページを読むだけの道具（許可がなくても通す）
READ_OPS = {
    "read_page", "get_page_text", "find", "read_console_messages", "read_network_requests",
    "tabs_context", "preview_list", "preview_logs", "shortcuts_list", "list_connected_browsers",
}
# タブの切り替えなど（許可がなくても通す。控えは捨てる）
TAB_OPS = {"tabs_create", "tabs_select", "tabs_close", "resize_window", "select_browser", "switch_browser"}
# 画面を操作する道具（computer）のうち、見るだけの動作
COMPUTER_READ_ACTIONS = {"screenshot", "zoom", "wait", "scroll", "scroll_to"}
# 種類の対応（画面の部品 → 制度データの欄の種類）
ROLE_KIND = {"checkbox": "チェック", "switch": "チェック", "radio": "ラジオ", "combobox": "選択", "listbox": "選択"}

_SAFE_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_WEB_URL = re.compile(r"^https?://")
_STAGE = re.compile(r"^[0-9]+_")


# ---- 道具の名前 ----

def tool_kind(tool_name: str) -> Optional[Tuple[str, str]]:
    """道具の名前から (ブラウザの種類, 動作の名前) を返す。対象の道具でなければ None。

    mcp__Claude_Browser__computer、mcp__remote-devices__claude-in-chrome__file_upload、
    mcp__computer-use__left_click のように、最後の「__」の後が動作の名前。
    Claude in Chrome の動作の名前の「_mcp」は外す（tabs_context_mcp → tabs_context）。
    """
    name = str(tool_name or "")
    if not any(marker in name for marker in ("Claude_Browser", "claude-in-chrome", "computer-use")):
        return None
    parts = name.split("__")
    if len(parts) < 3 or parts[0] != "mcp":
        return (UNKNOWN, name)
    server = "__".join(parts[1:-1])
    op = parts[-1]
    if op.endswith("_mcp"):
        op = op[: -len("_mcp")]
    if "computer-use" in server:
        return (COMPUTER_USE, op)
    if "claude-in-chrome" in server:
        return (CHROME, op)
    if "Claude_Browser" in server:
        return (BUILTIN, op)
    return (UNKNOWN, name)


def is_browser_tool(tool_name: str) -> bool:
    return tool_kind(tool_name) is not None


# ---- 許可と控えの置き場 ----

def _session_key(session_id) -> Optional[str]:
    if not session_id:
        return None
    text = str(session_id)
    if _SAFE_SESSION.match(text):
        return text
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def state_dir(folder: Path, session_id) -> Optional[Path]:
    key = _session_key(session_id)
    if key is None:
        return None
    return Path(folder) / company.MARKER_DIR / company.TEMP_DIR / STATE_DIR / key


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def has_permission(folder: Path, session_id) -> bool:
    directory = state_dir(folder, session_id)
    if directory is None:
        return False
    record = _read_json(directory / PERMISSION_FILE)
    return isinstance(record, dict) and record.get("session_id") == str(session_id)


def is_nyuryoku_prompt(prompt) -> bool:
    """担当者が `/hojokin:nyuryoku` を呼んだ文か。

    文の先頭が呼び出しのときだけにする。別のセッションから送られた文は、頭に知らせの印が付くので、
    許可にならない（実験 E1）。
    """
    text = unicodedata.normalize("NFC", str(prompt or "")).strip()
    if not text.startswith(NYURYOKU_COMMAND):
        return False
    rest = text[len(NYURYOKU_COMMAND):]
    return rest == "" or rest[0].isspace()


def _load_snapshots(folder: Path, session_id) -> Dict[str, dict]:
    directory = state_dir(folder, session_id)
    if directory is None:
        return {}
    value = _read_json(directory / SNAPSHOT_FILE)
    return value if isinstance(value, dict) else {}


def _save_snapshots(folder: Path, session_id, snapshots: Dict[str, dict]) -> None:
    directory = state_dir(folder, session_id)
    if directory is None:
        return
    _write_json(directory / SNAPSHOT_FILE, snapshots)


def discard_snapshot(folder: Path, session_id, kind: str) -> None:
    snapshots = _load_snapshots(folder, session_id)
    if kind in snapshots:
        del snapshots[kind]
        _save_snapshots(folder, session_id, snapshots)


# ---- 制度データの画面の定義 ----

class Scope:
    """押してよいボタンと、ツールが入れる欄（制度データの申請画面から作る）。"""

    def __init__(self) -> None:
        self.buttons: Set[str] = set()
        self.fields: Dict[str, Set[str]] = {}

    @classmethod
    def load(cls, folder: Path) -> "Scope":
        """`記録/制度データ/*.json` の申請画面を、すべて合わせる。読めないファイルは使わない（通す側に倒さない）。"""
        scope = cls()
        directory = Path(folder).joinpath(*SCHEME_DIR)
        try:
            files = sorted(p for p in directory.glob("*.json") if p.is_file())
        except OSError:
            files = []
        for path in files:
            data = _read_json(path)
            screens = ((data or {}).get("申請画面") or {}).get("画面") if isinstance(data, dict) else None
            if not isinstance(screens, list):
                continue
            for screen in screens:
                if not isinstance(screen, dict):
                    continue
                for button in screen.get("押してよいボタン") or []:
                    if isinstance(button, str) and normalize(button):
                        scope.buttons.add(normalize(button))
                for field in screen.get("欄") or []:
                    if not isinstance(field, dict) or field.get("担当者が入れる") is not False:
                        continue
                    name = normalize(field.get("名前"))
                    if name:
                        scope.fields.setdefault(name, set()).add(str(field.get("種類")))
        return scope


def _name_keys(name: str) -> List[str]:
    """画面の名前と照らす形（全体と、「：」より前の項目名）。"""
    keys = [name]
    for sep in ("：", ":"):
        if sep in name:
            head = normalize(name.split(sep, 1)[0])
            if head and head not in keys:
                keys.append(head)
    return keys


# ---- 判定 ----

class Denied(Exception):
    pass


class Context:
    """1回の判定で使うもの（許可・控え・制度データ）。要るときに読む。"""

    def __init__(self, data: dict, folder: Path, kind: str):
        self.data = data
        self.folder = Path(folder)
        self.kind = kind
        self.session_id = data.get("session_id")
        self._scope: Optional[Scope] = None
        self._snapshot = None
        self.discard = False

    @property
    def scope(self) -> Scope:
        if self._scope is None:
            self._scope = Scope.load(self.folder)
        return self._scope

    def require_permission(self) -> None:
        if not has_permission(self.folder, self.session_id):
            raise Denied(
                "画面入力の許可がないため、ブラウザでのクリック・入力・添付を止めました（hojokin プラグインの決まり）。"
                "画面入力は、担当者が「/hojokin:nyuryoku」を呼んだときだけ行えます。"
                "画面に入力したいときは、担当者に /hojokin:nyuryoku を選んでもらうよう案内してください。"
                "ページを読むことは、許可がなくてもできます。"
            )

    def element(self, tool_input: dict) -> Tuple[Page, str, dict]:
        ref = tool_input.get("ref")
        if self._snapshot is None:
            self._snapshot = _load_snapshots(self.folder, self.session_id).get(self.kind) or {}
        snapshot = self._snapshot
        elements = snapshot.get("elements") if isinstance(snapshot, dict) else None
        if not elements:
            raise Denied(
                "この画面の部品の控えがないため、止めました（hojokin プラグインの決まり）。"
                "部品の番号は画面ごとに振り直されるので、クリックやページの移動の後は控えを捨てています。"
                "先にページを読み直し（read_page。filter は all）、そこで分かった番号で操作してください。"
            )
        _check_tab(snapshot, tool_input.get("tabId"))
        if not ref:
            raise Denied("部品は番号（ref）で指してください。座標で指す操作は止めています（hojokin プラグインの決まり）。")
        page = Page(elements)
        element = page.get(str(ref))
        if element is None:
            raise Denied(
                f"番号 {ref} は、控えたページの部品にありません（hojokin プラグインの決まり）。"
                "ページを読み直し（read_page。filter は all）、そこで分かった番号で操作してください。"
            )
        return page, str(ref), element


def _check_tab(snapshot: dict, tab) -> None:
    """操作するタブが、控えを読んだタブと同じと分かるときだけ通す。

    - タブを指して（tabId を付けて）読んだ控えは、同じ tabId を付けた操作にだけ使う。
      tabId を省いた操作は、前に出ているタブで動くので、読んだタブと同じとは限らない。
    - タブを指さずに読んだ控えは、tabId を省いた操作か、読んだ結果の「Executed on tabId」と
      同じ tabId を付けた操作にだけ使う。
    """
    given = snapshot.get("tab_given")
    read_tab = snapshot.get("tab")
    if not isinstance(given, bool):
        raise Denied(
            "控えに、どのタブを読んだかがないため、止めました（hojokin プラグインの決まり）。"
            "ページを読み直し（read_page。filter は all）、そこで分かった番号で操作してください。"
        )
    if given:
        if tab is None:
            raise Denied(
                f"控えはタブ（tabId {read_tab}）を指して読んだものなので、操作にも同じ tabId を付けてください"
                "（hojokin プラグインの決まり）。tabId を省くと前に出ているタブで動くため、"
                "読んだタブと別のタブの部品を押すおそれがあります。"
            )
        if str(tab) != str(read_tab):
            raise Denied(
                "控えたページと別のタブを操作しようとしたため、止めました（hojokin プラグインの決まり）。"
                "操作するタブのページを読み直してから続けてください。"
            )
        return
    if tab is not None and (read_tab is None or str(tab) != str(read_tab)):
        raise Denied(
            "控えたページと別のタブを操作しようとしたため、止めました（hojokin プラグインの決まり）。"
            "控えはタブを指さずに読んだものです。操作するタブを tabId で指して読み直し、"
            "同じ tabId を付けて操作してください。"
        )


def _found_word(name: str, words: Tuple[str, ...]) -> Optional[str]:
    """名前に含む語（空白を除いて探す。「提 出」のような書き方ですり抜けないように）。"""
    compact = "".join(name.split())
    for word in words:
        if word in compact:
            return word
    return None


def _deny_button(name: str, why: str) -> Denied:
    return Denied(f"ボタン「{name}」は押せません。{why}（hojokin プラグインの決まり）。")


def _check_button(ctx: Context, element: dict) -> None:
    name = normalize(element.get("name"))
    if not name:
        raise Denied("名前の読めないボタン・リンクは押せません（hojokin プラグインの決まり）。担当者に押してもらってください。")
    word = _found_word(name, PROHIBITED_BUTTON_WORDS)
    if word:
        raise _deny_button(
            name,
            f"名前に「{word}」を含むボタンは、提出などにつながるので、ツールは押しません。"
            "ここまで入れた欄を担当者に示し、担当者に画面で確かめて押してもらってください",
        )
    if name not in ctx.scope.buttons:
        raise _deny_button(
            name,
            "制度データの申請画面の「押してよいボタン」にないボタンです。押す必要があれば、担当者に押してもらってください",
        )


def _check_choice(ctx: Context, page: Page, control_ref: str) -> None:
    control = page.get(control_ref) or {}
    name = page.field_name(control_ref)
    if not name:
        raise Denied(
            "名前の読めない欄（囲むラベルのない欄や、名前の空の選択欄）には入れません（hojokin プラグインの決まり）。"
            "担当者に、その欄を画面で入れてもらってください。"
        )
    word = _found_word(name, PROHIBITED_FIELD_WORDS)
    if word:
        raise Denied(
            f"欄「{name}」は、名前に「{word}」を含むので、ツールは入れません（hojokin プラグインの決まり）。"
            "確認・誓約・同意・宣誓の欄は担当者が入れます。入れるべき欄を担当者に示して止まってください。"
        )
    kinds: Set[str] = set()
    for key in _name_keys(name):
        kinds |= ctx.scope.fields.get(key, set())
    if not kinds:
        raise Denied(
            f"欄「{name}」は、制度データの申請画面で、ツールが入れる欄とされていません（hojokin プラグインの決まり）。"
            "担当者に入れてもらうか、入れる欄かを担当者に確かめてください。"
        )
    want = ROLE_KIND.get(control.get("role", ""))
    if want not in kinds:
        raise Denied(
            f"欄「{name}」は、制度データでは種類が「{'・'.join(sorted(kinds))}」で、画面の欄の種類と合いません"
            "（hojokin プラグインの決まり）。担当者に入れてもらってください。"
        )


def _deny_file_field() -> Denied:
    return Denied(
        "添付の欄は、クリックや入力では扱いません（hojokin プラグインの決まり）。"
        "Claude in Chrome では、添付の道具（file_upload）で、案件の「添付する書類」にある写しを添付してください。"
        "内蔵ブラウザでは添付できないので、担当者に、添付する書類の場所と欄を示して添付してもらってください。"
    )


def _resolve_control(page: Page, ref: str, element: dict) -> Optional[str]:
    """クリック・入力の行き先の欄。ラベルやラベルの中の文字を指したときは、ラベルの中の欄（1つだけのとき）。"""
    if element["role"] in CHOICE_ROLES + TEXT_ROLES or element.get("type") == "file":
        return ref
    label = page.enclosing_label(ref)
    if label is None:
        return None
    controls = page.controls_in(label)
    return controls[0] if len(controls) == 1 else None


def _check_click(ctx: Context, tool_input: dict) -> None:
    ctx.require_permission()
    if tool_input.get("coordinate") is not None or tool_input.get("start_coordinate") is not None:
        raise Denied("座標でのクリックは止めています（hojokin プラグインの決まり）。部品は番号（ref）で指してください。")
    if tool_input.get("modifiers"):
        raise Denied("キーを押しながらのクリックは止めています（hojokin プラグインの決まり）。")
    page, ref, element = ctx.element(tool_input)
    if element.get("type") == "file":
        raise _deny_file_field()
    if element["role"] in ("button", "link"):
        _check_button(ctx, element)
        return
    control = _resolve_control(page, ref, element)
    if control is None:
        raise Denied(
            "押してよいボタンか、ツールが入れる欄にだけ、クリックできます（hojokin プラグインの決まり）。"
            "この部品はどちらにも当たりません。"
        )
    target = page.get(control) or {}
    if target.get("type") == "file":
        raise _deny_file_field()
    if target.get("role") in TEXT_ROLES:
        raise Denied("文字の欄はクリックせず、入力の道具（form_input）で入れてください（hojokin プラグインの決まり）。")
    _check_choice(ctx, page, control)


def _check_form_input(ctx: Context, tool_input: dict) -> None:
    ctx.require_permission()
    page, ref, element = ctx.element(tool_input)
    if element.get("type") == "file":
        raise _deny_file_field()
    control = _resolve_control(page, ref, element)
    if control is None:
        raise Denied("この部品は、値を入れる欄ではありません（hojokin プラグインの決まり）。")
    target = page.get(control) or {}
    kind = target.get("type", "")
    if kind == "file":
        raise _deny_file_field()
    if target.get("role") in TEXT_ROLES:
        if kind == "password" or "パスワード" in page.field_name(control):
            raise Denied(
                "パスワードの欄には入れません（hojokin プラグインの決まり）。"
                "ログインは、担当者にブラウザで自分でしてもらってください。"
            )
        if kind == "hidden":
            raise Denied("隠れた欄には入れません（hojokin プラグインの決まり）。")
        return
    _check_choice(ctx, page, control)


def _is_attach_copy(parts: Tuple[str, ...]) -> bool:
    """`案件/` からの場所の部分が、段階のフォルダの「添付する書類」の中のファイルか。

    案件/<案件>/<段階>/添付する書類/<ファイル> と、段階の下にもう1段ある
    案件/<案件>/4_効果報告/1年目/添付する書類/<ファイル> の形（DESIGN 4.5）を通す。
    段階のフォルダの名前は「1_申請」の形（数字と _ で始まる）。「申請書」の下は通さない。
    """
    if len(parts) < 4 or not _STAGE.match(parts[1]):
        return False
    middle = parts[2:-1]
    if ATTACH_DIR not in middle or "申請書" in middle:
        return False
    # 「添付する書類」は、段階のすぐ下か、その下の1段（1年目など）の下に限る
    return middle.index(ATTACH_DIR) <= 1


def _check_upload(ctx: Context, tool_input: dict) -> None:
    ctx.require_permission()
    _page, _ref, element = ctx.element(tool_input)
    if element.get("type") != "file":
        raise Denied("添付の道具は、添付の欄（ファイルを選ぶ欄）にだけ使えます（hojokin プラグインの決まり）。")
    paths = tool_input.get("paths")
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths:
        raise Denied("添付するファイルの場所がありません（hojokin プラグインの決まり）。")
    cwd = Path(str(ctx.data.get("cwd") or ctx.folder))
    for raw in paths:
        target = Path(os.path.expanduser(str(raw)))
        if not target.is_absolute():
            target = cwd / target
        # 別名と「..」をたどった後に、`案件/` からの場所で見る（lib/places.py）
        try:
            parts = tuple(places.relative_inside(ctx.folder / CASE_DIR, target).split("/"))
        except places.PlaceError:
            parts = ()
        real = places.real(target)
        if not _is_attach_copy(parts) or not real.is_file():
            raise Denied(
                f"「{raw}」は添付できません（hojokin プラグインの決まり）。"
                "添付できるのは、案件の段階のフォルダの「添付する書類」にある写しだけです"
                "（例：案件/<案件>/1_申請/添付する書類/）。原本や、ほかの場所のファイルは添付しません。"
            )


def _batch_items(tool_input: dict) -> List[Tuple[str, dict]]:
    actions = tool_input.get("actions")
    if not isinstance(actions, list):
        raise Denied("まとめて動かす道具の中身が読めないため、止めました（hojokin プラグインの決まり）。")
    items = []
    for action in actions:
        if not isinstance(action, dict):
            raise Denied("まとめて動かす道具の中身が読めないため、止めました（hojokin プラグインの決まり）。")
        name = str(action.get("name") or action.get("tool") or "")
        op = name.split("__")[-1]
        if op.endswith("_mcp"):
            op = op[: -len("_mcp")]
        payload = action.get("input")
        if payload is None:
            payload = action.get("args") or {}
        if not isinstance(payload, dict):
            raise Denied("まとめて動かす道具の中身が読めないため、止めました（hojokin プラグインの決まり）。")
        items.append((op, payload))
    return items


def _changes_page(op: str, tool_input: dict) -> bool:
    if op == "navigate" or op in TAB_OPS:
        return True
    return op == "computer" and tool_input.get("action") == "left_click"


def _check_navigate(tool_input: dict) -> None:
    """移れるのは、http・https で始まる URL と、back・forward だけ。

    スキームのない形（localhost:8780 など）も拒む。「javascript:1,…」のように、
    スキームの名前の後に数字を続けた URL と見分けられないため。
    中に空白・制御文字（タブ・改行・ゼロ幅の文字など）を含む URL も拒む。
    ブラウザは URL の中のタブ・改行を捨てて読むので、「java<タブ>script:」がすり抜けないように。
    """
    raw = tool_input.get("url")
    url = str(raw if raw is not None else "").strip()
    if any(unicodedata.category(c)[0] in ("C", "Z") for c in url):
        raise Denied(
            "空白や制御文字（タブ・改行など）を含む URL には移れません（hojokin プラグインの決まり）。"
            "空白は %20 のように書き換えた http・https の URL で指してください。"
        )
    lower = url.lower()
    if lower in ("back", "forward") or _WEB_URL.match(lower):
        return
    raise Denied(
        f"「{url}」には移れません。移れるのは http:// か https:// で始まるページと、"
        "back・forward だけです（hojokin プラグインの決まり）。"
        "スキームのない名前（localhost:8780 など）は、http:// を付けて指してください。"
    )


def _judge(ctx: Context, op: str, tool_input: dict, in_batch: bool = False) -> None:
    if op in READ_OPS:
        return
    if op in TAB_OPS:
        ctx.discard = True
        return
    if op == "navigate":
        _check_navigate(tool_input)
        ctx.discard = True
        return
    if op == "computer":
        action = tool_input.get("action")
        if action in COMPUTER_READ_ACTIONS:
            return
        if action == "left_click":
            _check_click(ctx, tool_input)
            ctx.discard = True
            return
        raise Denied(
            f"画面の操作「{action}」は止めています（hojokin プラグインの決まり）。"
            "ダブルクリック・右クリック・ドラッグ、打ち込み、キーは使えません。"
            "欄には入力の道具（form_input）で入れ、ボタンは番号（ref）で指してクリックしてください。"
        )
    if op == "form_input":
        _check_form_input(ctx, tool_input)
        return
    if op == "file_upload":
        _check_upload(ctx, tool_input)
        return
    if op == "browser_batch":
        if in_batch:
            raise Denied("まとめて動かす道具の中に、まとめて動かす道具は入れられません（hojokin プラグインの決まり）。")
        items = _batch_items(tool_input)
        moves = [i for i, (item_op, item_input) in enumerate(items) if _changes_page(item_op, item_input)]
        if len(moves) > 1 or (moves and moves[0] != len(items) - 1):
            raise Denied(
                "まとめて動かす道具では、クリックやページの移動は1回までで、最後に置いてください（hojokin プラグインの決まり）。"
                "前の画面の控えで、次の画面の部品を押させないためです。"
            )
        for item_op, item_input in items:
            _judge(ctx, item_op, item_input, in_batch=True)
        return
    if op in ("javascript_tool", "javascript", "shortcuts_execute"):
        raise Denied("JavaScript とショートカットの実行は止めています（hojokin プラグインの決まり）。")
    raise Denied(
        f"ブラウザの道具「{op}」は、画面入力の守りで通してよいものに入っていないため、止めました（hojokin プラグインの決まり）。"
    )


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


# ---- hooks から呼ぶもの ----

def pre_tool_use(data: dict, folder: Path) -> Optional[dict]:
    found = tool_kind(data.get("tool_name"))
    if found is None:
        return None
    kind, op = found
    if kind == COMPUTER_USE:
        return _deny(
            "会社のフォルダでは、画面を操作する機能（computer use）は使えません（hojokin プラグインの決まり）。"
            "画面入力は、担当者が /hojokin:nyuryoku を呼んだうえで、Claude in Chrome か内蔵ブラウザの道具で行ってください。"
        )
    if kind == UNKNOWN:
        return _deny(f"知らないブラウザの道具（{op}）なので、止めました（hojokin プラグインの決まり）。")
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return _deny("ブラウザの道具の入力が読めないため、止めました（hojokin プラグインの決まり）。")
    ctx = Context(data, folder, kind)
    try:
        _judge(ctx, op, tool_input)
    except Denied as denied:
        return _deny(str(denied))
    if ctx.discard:
        discard_snapshot(folder, ctx.session_id, kind)
    return None


def post_tool_use(data: dict, folder: Path) -> None:
    found = tool_kind(data.get("tool_name"))
    if found is None:
        return None
    kind, op = found
    if kind in (COMPUTER_USE, UNKNOWN):
        return None
    session_id = data.get("session_id")
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    if op == "read_page":
        tree = parse(response_text(data.get("tool_response")))
        snapshots = _load_snapshots(folder, session_id)
        if tree["elements"]:
            tab = tool_input.get("tabId")
            snapshots[kind] = {
                "tab": str(tab) if tab is not None else tree["tab"],
                # タブを指して読んだか（指して読んだ控えは、同じ tabId を付けた操作にだけ使う）
                "tab_given": tab is not None,
                "elements": tree["elements"],
                "time": int(time.time()),
            }
        else:
            snapshots.pop(kind, None)
        _save_snapshots(folder, session_id, snapshots)
        return None
    changed = _changes_page(op, tool_input)
    if op == "browser_batch":
        try:
            changed = any(_changes_page(o, i) for o, i in _batch_items(tool_input))
        except Denied:
            changed = True
    if changed:
        discard_snapshot(folder, session_id, kind)
    return None


def user_prompt_submit(data: dict, folder: Path) -> None:
    if not is_nyuryoku_prompt(data.get("prompt")):
        return None
    session_id = data.get("session_id")
    directory = state_dir(folder, session_id)
    if directory is None:
        return None
    _write_json(directory / PERMISSION_FILE, {"session_id": str(session_id), "time": int(time.time())})
    return None
