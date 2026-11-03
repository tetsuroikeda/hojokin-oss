"""実験 E5 の2：dulwich（Python だけで動く Git）で、版の管理（SPEC 共通の要件、DESIGN 10章）が足りるか。

使い方：<venv の python3> dulwich_check.py <作業用の一時フォルダ>
git のコマンドは使わない。一時フォルダに試しの会社のフォルダを作り、次を順に確かめて結果を出す。
1. 履歴を作る（送り先なし）  2. ツール・社長のそれぞれの名前で残す  3. 社長が手で変えたファイルを見つける
4. 履歴の一覧（日時・書類・理由・だれ）  5. 前の版を取り出す  6. 戻したことを新しい記録として残す
7. 提出版の印と取り出し  8. .gitignore（画面入力の許可は履歴に入れない）  9. 名前の文字（日本語、濁点の分かれた形）
10. 送り先の設定が0件  11. 大きなファイルと多いファイルの速さ
"""

import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dulwich import porcelain
from dulwich.objects import Commit
from dulwich.repo import Repo

JST = timezone(timedelta(hours=9))
TOOL = "ツール <tool@hojokin.invalid>"
OWNER = "社長 <owner@hojokin.invalid>"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("できた" if ok else "できない") + f"｜{name}｜{detail}")


def commit(repo, message, who):
    """変わったファイルをすべて加え、だれの変更かを付けて残す。"""
    porcelain.add(repo)
    return porcelain.commit(repo, message=message.encode("utf-8"), author=who.encode("utf-8"),
                            committer=who.encode("utf-8"))


def changed_paths(repo):
    st = porcelain.status(repo, untracked_files="all")
    staged = [p for paths in st.staged.values() for p in paths]
    return sorted({p.decode("utf-8") if isinstance(p, bytes) else p for p in staged + st.unstaged + st.untracked})


def file_at(repo, commit_id, path):
    tree = repo[repo[commit_id].tree]
    obj = repo.object_store
    from dulwich.object_store import tree_lookup_path
    _mode, sha = tree_lookup_path(obj.__getitem__, tree.id, path.encode("utf-8"))
    return repo[sha].data


def main():
    work = Path(sys.argv[1])
    folder = work / "試しの会社"
    if folder.exists():
        raise SystemExit(f"{folder} がすでにあります。空の一時フォルダを渡してください")
    plan = folder / "案件" / "2026_省力化（一般型）第9回" / "1_申請" / "申請書" / "計画書その1.docx"
    plan.parent.mkdir(parents=True)
    (folder / "原本" / "見積・契約・請求").mkdir(parents=True)
    (folder / "記録").mkdir()
    (folder / ".hojokin").mkdir()
    plan.write_bytes(b"version-1")
    (folder / "原本" / "見積・契約・請求" / "2026-10-20_見積書_〇〇機械.pdf").write_bytes(b"%PDF-1.4 original")
    (folder / "記録" / "会社の記録.json").write_text('{"スキーマの版": 1, "項目": []}', encoding="utf-8")
    (folder / ".gitignore").write_text(".hojokin/画面入力の許可.json\n.hojokin/部品の控え.json\n見るだけ/\n",
                                       encoding="utf-8")
    (folder / ".hojokin" / "画面入力の許可.json").write_text("{}", encoding="utf-8")

    # 1. 履歴を作る
    repo = porcelain.init(str(folder))
    check("1 履歴を作る", (folder / ".git").is_dir(), "porcelain.init")

    # 2. ツールの名前で残す
    c1 = commit(repo, "会社のフォルダを用意した（社長の依頼：会社のフォルダにして）", TOOL)
    check("2 ツールとして残す", repo[c1].author.decode("utf-8") == TOOL, repo[c1].author.decode("utf-8"))

    # 3. 社長が手で変えたファイルを見つけて、社長として残す
    time.sleep(1)
    plan.write_bytes(b"version-2 owner edit")
    changed = changed_paths(repo)
    expect = "案件/2026_省力化（一般型）第9回/1_申請/申請書/計画書その1.docx"
    check("3 社長が手で変えたファイルを見つける", changed == [expect], str(changed))
    c2 = commit(repo, "社長が手で変更", OWNER)
    time.sleep(1)
    plan.write_bytes(b"version-3 tool edit")
    c3 = commit(repo, "計画書の3章を直した（社長の依頼：数字をそろえて）", TOOL)

    # 4. 履歴の一覧
    rows = []
    for entry in repo.get_walker(paths=[expect.encode("utf-8")]):
        c = entry.commit
        when = datetime.fromtimestamp(c.author_time, JST).strftime("%Y-%m-%d %H:%M")
        files = [ch.new.path.decode("utf-8") for ch in entry.changes() if ch.new and ch.new.path]
        rows.append((when, c.author.decode("utf-8").split(" <")[0], c.message.decode("utf-8"), files))
    check("4 書類ごとの履歴（日時・だれ・理由・書類）", len(rows) == 3 and rows[0][1] == "ツール" and rows[1][1] == "社長",
          json.dumps(rows, ensure_ascii=False))

    # 5. 前の版を取り出す（作業のファイルは変えない）
    old = file_at(repo, c2, expect)
    check("5 前の版を取り出す", old == b"version-2 owner edit" and plan.read_bytes() == b"version-3 tool edit", repr(old))

    # 6. 戻す（履歴は書き換えず、戻したことを新しい記録にする）
    plan.write_bytes(old)
    c4 = commit(repo, f"1つ前の版（{c2.decode()[:7]}）に戻した（社長の依頼：1つ前に戻して）", TOOL)
    ids = [entry.commit.id for entry in repo.get_walker()]
    # 用意・社長の変更・ツールの変更・戻した記録の4件。戻す前の版（c3）も履歴に残る
    check("6 戻したことを新しい記録として残す",
          plan.read_bytes() == old and ids == [c4, c3, c2, c1] and file_at(repo, c3, expect) == b"version-3 tool edit",
          f"履歴 {len(ids)} 件")

    # 7. 提出版の印（日本語のタグ名）と取り出し
    tag = "提出版/2026_省力化（一般型）第9回/1_申請".encode("utf-8")
    porcelain.tag_create(repo, tag, author=TOOL.encode("utf-8"), message="提出した".encode("utf-8"), annotated=True)
    plan.write_bytes(b"version-5 after submit")
    commit(repo, "提出の後に直した", TOOL)
    tagged = repo[repo.refs[b"refs/tags/" + tag]]
    check("7 提出版の印と取り出し", file_at(repo, tagged.object[1], expect) == old,
          tag.decode("utf-8"))

    # 8. .gitignore にある画面入力の許可は履歴に入らない
    tree_paths = [p.decode("utf-8") for p in porcelain.ls_files(repo)]
    check("8 .gitignore で履歴に入れないファイル", ".hojokin/画面入力の許可.json" not in tree_paths,
          f"{len(tree_paths)} 件：" + ", ".join(tree_paths))

    # 9. 名前の文字。Finder などで作られた、濁点の分かれた形（NFD）の名前
    nfd = unicodedata.normalize("NFD", "ガイドブック_見積書.pdf")
    (folder / "原本" / nfd).write_bytes(b"%PDF nfd")
    found = changed_paths(repo)
    commit(repo, "書類を入れた", TOOL)
    stored = [p for p in (x.decode("utf-8") for x in porcelain.ls_files(repo)) if "見積書.pdf" in p and "ブ" in
              unicodedata.normalize("NFC", p)]
    forms = ["NFC" if unicodedata.is_normalized("NFC", p) else "NFD" for p in stored]
    after = changed_paths(repo)
    check("9 濁点の分かれた名前のファイル", bool(stored) and after == [],
          f"見つけた {found}／残した形 {forms}／残した後の変更 {after}")

    # 10. 送り先（リモート）の設定
    config = repo.get_config()
    remotes = [s for s in config.sections() if s and s[0] == b"remote"]
    check("10 送り先の設定が0件", remotes == [], str(remotes))

    # 11. 速さ：5MB の PDF 1つと、小さなファイル300件
    big = folder / "原本" / "決算・税" / "決算書_5MB.pdf"
    big.parent.mkdir(parents=True)
    big.write_bytes(os.urandom(5 * 1024 * 1024))
    many = folder / "入れ口"
    many.mkdir()
    for i in range(300):
        (many / f"写真_{i:03d}.txt").write_text(f"写真の説明 {i}", encoding="utf-8")
    t = time.time()
    commit(repo, "書類をまとめて入れた", TOOL)
    t_commit = time.time() - t
    t = time.time()
    changed_paths(repo)
    t_status = time.time() - t
    check("11 速さ（5MB と300件）", t_commit < 30 and t_status < 10,
          f"残すのに {t_commit:.1f} 秒、変更を探すのに {t_status:.1f} 秒")

    print()
    print(f"Python {sys.version.split()[0]}、dulwich {'.'.join(map(str, __import__('dulwich').__version__))}")
    print(f"できた {sum(ok for _, ok, _ in results)} / {len(results)}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
