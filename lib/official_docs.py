"""公式資料を公式サイトから取り、案件のフォルダに置いて、ページごとの文字にする（SPEC F3、DESIGN 9.2、TASKS M2a）。

流れ：
1. 取る資料の一覧（Claude が公式サイトのダウンロードのページで確かめて作る。形は load_list の説明）を受け取る。
2. 案件のフォルダ `案件/<案件の名前>/公式資料/` を作り、資料を取って置く。置いたファイルは読み取り専用にする（DESIGN 5章）。
   - 前に取ったものと同じ中身なら、そのままにする。
   - 前に取ったものと中身が違えば、上書きしない（改訂の扱いは F7。前のものを残し、違うことを知らせる）。
   - 返ってきた中身が、拡張子の形と合わないとき（PDF のはずがウェブページだった、など）は置かない。
3. `記録/資料の本文/<案件の名前>/<資料の id>/` に、ページごとの文字と、印刷されたページ番号との対応を置く（lib/doc_text.py）。
4. `記録/資料の本文/<案件の名前>/資料の一覧.json` に、資料ごとの id・名前・公募回・版・URL・取得日・ハッシュ・
   ページのずれ・注記を、制度データの「資料」と同じ形で残す（M2c がそのまま制度データに写せるように）。
5. 案件の回の資料が一つもなければ（まだ公表されていない）、「直近回である第◯回の資料に基づいている」と示す（SPEC F3）。
   回の違う資料（第6回版の手引きなど）も、資料ごとに示す。

通信は、標準のライブラリ（urllib）だけで行う。版の履歴に残すのは、応答の終わりの hook（ツールの版）に任せる。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from lib import case_folder, dates, doc_text

RECORDS_DIR = "記録"  # lib/company_init.py の RECORDS_DIR と同じ
TEXT_DIR = "資料の本文"
LIST_FILE = "資料の一覧.json"
TEMP_PREFIX = ".取得中_"
USER_AGENT = "Mozilla/5.0 (compatible; hojokin-plugin)"
TIMEOUT_SECONDS = 60
MAX_BYTES = 200 * 1024 * 1024
READ_ONLY = 0o444

# 状態（社長に見える言葉）
GOT = "取った"
SAME = "前と同じ"
CHANGED = "前と中身が違う"
FAILED = "取れなかった"

ZIP_SUFFIXES = (".docx", ".xlsx", ".xlsm", ".pptx", ".zip")
OLE_SUFFIXES = (".doc", ".xls", ".ppt")
KNOWN_SUFFIXES = doc_text.SUPPORTED_SUFFIXES + ZIP_SUFFIXES + OLE_SUFFIXES
CONTENT_TYPE_SUFFIX = (
    ("application/pdf", ".pdf"),
    ("text/html", ".html"),
    ("application/xhtml+xml", ".html"),
    ("wordprocessingml", ".docx"),
    ("spreadsheetml", ".xlsx"),
    ("application/msword", ".doc"),
    ("application/vnd.ms-excel", ".xls"),
    ("application/zip", ".zip"),
)
_ID = re.compile(r"^[^/\\:*?\"<>|\x00-\x1f.][^/\\:*?\"<>|\x00-\x1f]{0,59}$")
_ROUND = re.compile(r"第\s*(\d+)\s*回")


class ListError(ValueError):
    """取る資料の一覧の形が違う。"""


@dataclass
class DocResult:
    doc: Dict
    status: str
    message: str = ""
    file: str = ""  # 会社のフォルダからの場所
    sha256: str = ""
    text_dir: str = ""
    text_index: Optional[Dict] = None
    text_error: str = ""


@dataclass
class FetchResult:
    case: str
    seido: Dict
    made: List[str] = field(default_factory=list)
    docs: List[DocResult] = field(default_factory=list)
    notices: List[str] = field(default_factory=list)
    based_on_latest: bool = False
    list_file: str = ""

    @property
    def complete(self) -> bool:
        """資料がすべてそろい、文字にすべきものはすべて文字にできた。"""
        return all(d.status in (GOT, SAME) and not d.text_error for d in self.docs)


# ---- 一覧 ----


def round_number(text: str) -> Optional[int]:
    m = _ROUND.search(unicodedata.normalize("NFKC", text or ""))
    return int(m.group(1)) if m else None


def _require_text(obj: Dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ListError(f"{where}の「{key}」がありません")
    return value.strip()


def load_list(data: object) -> Dict:
    """取る資料の一覧を確かめて返す。形：

    {
      "制度": {"名前": "中小企業省力化投資補助金", "略称": "省力化", "枠": "一般型", "種類": "補助金", "公募回": "第9回"},
      "案件の名前": "2026_省力化（一般型）第9回",   ← なくてよい（年_略称（枠）公募回 で作る）
      "資料": [{"id": "要領8", "名前": "公募要領", "公募回": "第8回", "URL": "https://…", "版": "…", "注記": "…"}, …]
    }
    制度の「公募回」は、申請する回（案件の回）。資料の「公募回」は、その資料そのものの回。
    """
    if not isinstance(data, dict):
        raise ListError("取る資料の一覧は、{ } で囲んだ形にしてください")
    seido = data.get("制度")
    if not isinstance(seido, dict):
        raise ListError("「制度」がありません")
    _require_text(seido, "名前", "制度")
    _require_text(seido, "公募回", "制度")
    docs = data.get("資料")
    if not isinstance(docs, list) or not docs:
        raise ListError("「資料」に、取る資料を1つ以上並べてください")
    ids, files = set(), set()
    for i, doc in enumerate(docs, 1):
        where = f"資料の{i}つ目"
        if not isinstance(doc, dict):
            raise ListError(f"{where}が {{ }} で囲んだ形ではありません")
        doc_id = _require_text(doc, "id", where)
        if not _ID.match(doc_id):
            raise ListError(f"{where}の id（{doc_id}）に、フォルダの名前に使えない文字があるか、長すぎます")
        if doc_id in ids:
            raise ListError(f"id（{doc_id}）が2回出てきます")
        ids.add(doc_id)
        _require_text(doc, "名前", where)
        _require_text(doc, "公募回", where)
        url = _require_text(doc, "URL", where)
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ListError(f"{where}の URL（{url}）は、http か https で始まるウェブの場所にしてください")
        for key in ("版", "注記"):
            if key in doc and not isinstance(doc[key], str):
                raise ListError(f"{where}の「{key}」は文字にしてください")
        stem = file_stem(doc)
        if stem in files:
            raise ListError(f"{where}のファイルの名前（{stem}）が、ほかの資料と同じになります。名前か公募回を変えてください")
        files.add(stem)
    name = data.get("案件の名前")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise ListError("「案件の名前」は文字にしてください")
    return data


def file_stem(doc: Dict) -> str:
    """公式資料のファイルの名前（拡張子なし）。例：公募要領_第8回"""
    return case_folder.safe_name(f"{doc['名前']}_{doc['公募回']}")


def round_notices(seido: Dict, docs: List[Dict]):
    """回についての案内。（案件の回の資料がなく、直近回の資料に基づくか、案内の文の一覧）を返す。"""
    target = seido.get("公募回", "")
    target_n = round_number(target)
    numbered = [(d, round_number(d.get("公募回", ""))) for d in docs]
    rounds = sorted({n for _d, n in numbered if n is not None})
    notices: List[str] = []
    based_on_latest = False
    base_n = target_n
    if target_n is not None and rounds and target_n not in rounds:
        earlier = [n for n in rounds if n < target_n]
        base_n = max(earlier) if earlier else max(rounds)
        based_on_latest = True
        notices.append(
            f"{target}の資料はまだ公表されていないため、直近回である第{base_n}回の資料に基づいています。"
            f"{target}の資料が公表されたら、取り直して作り直します。")
    for d, n in numbered:
        if n is not None and n != base_n:
            notices.append(f"「{d['名前']}」は、{d['公募回']}の資料に基づいています。")
    return based_on_latest, notices


# ---- 取る ----


def _suffix_for(url: str, content_type: str, head: bytes) -> str:
    path = urllib.parse.urlsplit(url).path
    suffix = os.path.splitext(urllib.parse.unquote(path))[1].lower()
    if suffix in KNOWN_SUFFIXES:
        return suffix
    ctype = (content_type or "").lower()
    for key, value in CONTENT_TYPE_SUFFIX:
        if key in ctype:
            return value
    if head.lstrip().startswith(b"%PDF-"):
        return ".pdf"
    if head.lstrip()[:1] == b"<":
        return ".html"
    return ""


def _looks_like(suffix: str, content_type: str, head: bytes) -> str:
    """中身が拡張子の形と合うか。合わなければ、その理由（社長に見える文）。"""
    stripped = head.lstrip()
    is_html = "html" in (content_type or "").lower() or stripped[:15].lower().startswith((b"<!doctype", b"<html"))
    if suffix == ".pdf":
        if b"%PDF-" in head[:1024]:
            return ""
        if is_html:
            return "PDF のはずが、ウェブページが返ってきました（資料の場所が変わったか、なくなった可能性があります）"
        return "PDF の形ではありませんでした"
    if suffix in ZIP_SUFFIXES:
        if head.startswith(b"PK\x03\x04"):
            return ""
        if is_html:
            return "Word・Excel のはずが、ウェブページが返ってきました（資料の場所が変わったか、なくなった可能性があります）"
        return "Word・Excel の形ではありませんでした"
    if suffix in OLE_SUFFIXES:
        return "" if head.startswith(b"\xd0\xcf\x11\xe0") else "古い形の Word・Excel ではありませんでした"
    if suffix in doc_text.HTML_SUFFIXES:
        return "" if (is_html or stripped[:1] == b"<") else "ウェブページの形ではありませんでした"
    return "ファイルの形が分かりませんでした"


def download(url: str, dest: Path, timeout: int = TIMEOUT_SECONDS, max_bytes: int = MAX_BYTES) -> str:
    """url の中身を dest に書き、Content-Type を返す。取れなければ OSError（理由は社長に見える文）。"""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(dest, "wb") as out:
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise OSError(f"大きすぎるため、途中でやめました（{max_bytes // (1024 * 1024)}MB まで）")
                out.write(chunk)
            return response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        hint = "ページが見つかりません" if e.code == 404 else "サイトが応じませんでした"
        raise OSError(f"HTTP {e.code}：{hint}") from e
    except urllib.error.URLError as e:
        raise OSError(f"サイトにつながりませんでした（{e.reason}）") from e
    except (socket.timeout, TimeoutError) as e:
        raise OSError(f"{timeout}秒待っても応答がありませんでした") from e
    except ssl.SSLError as e:
        raise OSError(f"安全な通信（https）を始められませんでした（{e}）") from e


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing(official: Path, stem: str) -> Optional[Path]:
    for path in sorted(official.glob(f"{stem}.*")):
        if path.is_file() and not path.name.startswith(TEMP_PREFIX) and path.stem == stem:
            return path
    return None


def fetch_one(company: Path, official: Path, doc: Dict,
              downloader: Callable[[str, Path], str] = download) -> DocResult:
    stem = file_stem(doc)
    temp = official / f"{TEMP_PREFIX}{stem}"
    try:
        try:
            content_type = downloader(doc["URL"], temp)
        except OSError as e:
            return DocResult(doc, FAILED, str(e))
        with open(temp, "rb") as f:
            head = f.read(2048)
        suffix = _suffix_for(doc["URL"], content_type, head)
        problem = _looks_like(suffix, content_type, head) if suffix else "ファイルの形が分かりませんでした"
        if problem:
            return DocResult(doc, FAILED, problem)
        digest = sha256_of(temp)
        target = official / f"{stem}{suffix}"
        before = _existing(official, stem)
        if before is not None:
            rel = str(before.relative_to(company))
            if before.suffix.lower() == suffix and sha256_of(before) == digest:
                return DocResult(doc, SAME, "前に取ったものと同じ中身でした", rel, digest)
            return DocResult(
                doc, CHANGED,
                "前に取ったものと中身が違いました。改訂された可能性があります。前のものを残し、新しいものは置いていません",
                rel, sha256_of(before))
        os.replace(temp, target)
        target.chmod(READ_ONLY)
        return DocResult(doc, GOT, "", str(target.relative_to(company)), digest)
    finally:
        if temp.exists():
            temp.unlink()


def _text_dir(company: Path, case: str, doc_id: str) -> Path:
    return company / RECORDS_DIR / TEXT_DIR / case_folder.safe_name(case) / doc_id


def make_text(company: Path, case: str, result: DocResult) -> None:
    """取った資料を、ページごとの文字にする。前に文字にした中身と同じなら、そのままにする。"""
    if result.status not in (GOT, SAME) or not result.file:
        return
    source = company / result.file
    out = _text_dir(company, case, result.doc["id"])
    result.text_dir = str(out.relative_to(company))
    if source.suffix.lower() not in doc_text.SUPPORTED_SUFFIXES:
        result.text_dir = ""
        return
    if (out / doc_text.INDEX_FILE).exists():
        try:
            index = doc_text.load_index(out)
        except ValueError:
            index = {}
        if index.get("ハッシュ") == result.sha256:
            result.text_index = index
            return
    doc = dict(result.doc, ハッシュ=result.sha256)
    try:
        result.text_index = doc_text.write_text(source, out, doc, result.file)
    except doc_text.TextError as e:
        result.text_error = str(e)


def _list_entry(result: DocResult, today: str, previous: Optional[Dict]) -> Dict:
    """制度データの「資料」と同じ形の1件。"""
    doc = result.doc
    entry = {"id": doc["id"], "名前": doc["名前"], "公募回": doc["公募回"]}
    if doc.get("版"):
        entry["版"] = doc["版"]
    entry["URL"] = doc["URL"]
    same_as_before = previous is not None and previous.get("ハッシュ") == result.sha256
    entry["取得日"] = previous["取得日"] if same_as_before and previous.get("取得日") else today
    entry["ハッシュ"] = result.sha256
    offset = (result.text_index or {}).get("ページのずれ")
    if isinstance(offset, int):
        entry["ページのずれ"] = offset
    if doc.get("注記"):
        entry["注記"] = doc["注記"]
    return entry


def write_list(company: Path, case: str, seido: Dict, results: List[DocResult], based_on_latest: bool,
               notices: List[str], today: str) -> Path:
    """資料の一覧.json を書く。前の一覧にあって今回取らなかった資料は残す。"""
    path = company / RECORDS_DIR / TEXT_DIR / case_folder.safe_name(case) / LIST_FILE
    previous: Dict = {}
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            previous = {}
    entries = {e.get("id"): e for e in previous.get("資料", []) if isinstance(e, dict)}
    places = dict(previous.get("置き場所", {}))
    for r in results:
        old = entries.get(r.doc["id"])
        if r.status in (GOT, SAME):
            entries[r.doc["id"]] = _list_entry(r, today, old)
            places[r.doc["id"]] = {"ファイル": r.file, "本文": r.text_dir}
    data = {
        "案件": case,
        "制度": seido,
        "案件の回": seido.get("公募回"),
        "直近回の資料に基づく": based_on_latest,
        "案内": notices,
        "資料": list(entries.values()),
        "置き場所": places,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def fetch_all(company: Path, data: Dict, downloader: Callable[[str, Path], str] = download) -> FetchResult:
    """一覧の資料をすべて取り、案件のフォルダに置いて、文字にする。company は会社のフォルダ（目印を確かめた後）。"""
    data = load_list(data)
    seido = data["制度"]
    today = dates.today(company)
    case = case_folder.safe_name(data.get("案件の名前") or case_folder.case_name(seido, today.year))
    result = FetchResult(case=case, seido=seido)
    result.made = case_folder.ensure_case(company, case)
    official = case_folder.official_dir(company, case)
    for doc in data["資料"]:
        r = fetch_one(company, official, doc, downloader)
        make_text(company, case, r)
        result.docs.append(r)
    result.based_on_latest, result.notices = round_notices(seido, data["資料"])
    path = write_list(company, case, seido, result.docs, result.based_on_latest, result.notices, today.isoformat())
    result.list_file = str(path.relative_to(company))
    return result


# ---- 結果の文 ----


def _pages_label(r: DocResult) -> str:
    index = r.text_index or {}
    if r.text_error:
        return f"文字にできなかった（{r.text_error}）"
    if not index:
        return "文字にしない形" if r.status in (GOT, SAME) else "—"
    kind = index.get("種類")
    if kind != "PDF":
        return f"{kind}（{index.get('ページ数')}つ）" if kind == "Excel" else kind
    offset = index.get("ページのずれ")
    label = f"{index.get('ページ数')}ページ"
    if offset is None:
        label += "、印刷された番号は見つからず PDF のページで示す"
    elif offset == 0:
        label += "、印刷された番号は PDF のページと同じ"
    else:
        label += f"、印刷された番号は PDF のページより {offset} 小さい"
    empty = index.get("文字を取り出せないページ") or []
    if empty:
        label += f"、文字のないページ {len(empty)}（画像で読む）"
    return label


def report(result: FetchResult) -> str:
    lines = []
    if result.complete:
        lines.append(f"公式資料を取りました（案件：{result.case}）。資料はすべてそろいました。")
    else:
        lines.append(f"公式資料を取りました（案件：{result.case}）。まだそろっていない資料があります。")
    lines.append("")
    for notice in result.notices:
        lines.append(f"- {notice}")
    lines.append(f"- 書類フォルダ：{case_folder.CASES_DIR}/{result.case}/（公式資料は {case_folder.OFFICIAL_DIR}/ に、読み取り専用で置いた）")
    lines.append(f"- ページごとの文字：{RECORDS_DIR}/{TEXT_DIR}/{result.case}/（出典は印刷されたページ番号で示す）")
    lines.append(f"- 資料の一覧：{result.list_file}")
    lines.append("")
    lines.append("| 資料 | 資料の回 | 結果 | ページ |")
    lines.append("|---|---|---|---|")
    for r in result.docs:
        status = r.status + (f"：{r.message}" if r.status != GOT and r.message else "")
        lines.append(f"| {r.doc['名前']}（{r.doc['id']}） | {r.doc['公募回']} | {status} | {_pages_label(r)} |")
    missing = [r for r in result.docs if r.status == FAILED]
    changed = [r for r in result.docs if r.status == CHANGED]
    if missing:
        lines.append("")
        lines.append("取れなかった資料は、公式サイトのダウンロードのページで場所を確かめ直してから、もう一度取ってください。")
        for r in missing:
            lines.append(f"- {r.doc['名前']}：{r.doc['URL']}（{r.message}）")
    if changed:
        lines.append("")
        lines.append("前に取ったものと中身が違う資料があります。公募要領の改訂かもしれないので、社長に知らせてください。")
        for r in changed:
            lines.append(f"- {r.doc['名前']}：{r.file}")
    return "\n".join(lines) + "\n"
