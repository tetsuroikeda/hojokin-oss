# デモ動画（ハッカソン提出用）

hojokin の紹介動画を、コードで作る道具です。映像・字幕・BGM はこのフォルダのスクリプトから作り、声は音声合成（Gemini、予備に macOS の say）で作ります。プラグインには入りません。

- 長さ：約2分40秒（提出の条件は3分以内・日本語）
- 構成：社長の道のり（申請の5つの段階と、それぞれの壁）→ hojokin → 段階ごとの解決（実物の出力）→ PM のように自分から知らせる（実際の Claude Code の端末）→ その仕組み（フック）→ 学習 → 始め方 → 作り方と守り → 終わり

## 何が実物か

画面と文は、架空のデモの会社（株式会社やまぶき惣菜）で、実際にプラグインを動かして得たものです。

| 場面 | 出しているもの | どこから |
|---|---|---|
| 1 探す | 補助金の候補.docx | 保存した状態「1件目を終えた」の会社のフォルダ |
| 2 調べる | 概要と流れ.docx（出典のページつき） | 同上 |
| 3 書類 | 整理した後の原本の置き場、不備の一覧 | 対話/shorui.md（不備を仕込んだ書類14件を入れて「確認して」と頼んだ実際の応答） |
| 4 書く | 財務モデル.xlsx、計画書、根拠対照表.xlsx、審査役の確かめる観点 | 会社のフォルダ、agents/shinsa.md |
| 5 採択後 | 今の状態.html の工程表、差し戻しの通知（模擬の画面） | 会社のフォルダ、testdata/計画書/材料/5_差し戻し |
| PM | 「今日は何から？」と聞いたときの Claude Code の端末 | 対話/pm_terminal.json（rec_terminal.py が疑似端末で本物の claude を動かし、出たバイト列と時刻を記録。xterm.js で描き直す。待ち時間は詰める） |
| 仕組み | フックが Claude に渡す指示の文 | 対話/session_start.md（開いたときの hook の実際の出力） |
| 学習 | 覚えた事実・書き方の決まり・1件目の質問、2件目の決まり | 記録/会社の記録.json、記録/質問の記録.json、対話/session_start.md |
| 作り方 | コミット・タスク・eval のケース・テストの関数の数 | git log、docs/TASKS.md、evals/、tests/（2026-11-06 に数えた） |

- 対話の引用は、`素材.json` に写した文が `対話/` の記録にそのままあるかを、build.py が確かめます。
- 学習の場面の記録（事実118件・決まり7件・質問128件）は、保存した状態を戻す道具（evals/_lib/fukugen.py）が、回答表と1件目の指摘から製品の記録の道具で入れたものです。
- 冒頭の社長の道のりと、STEP 4 の確かめの印（！→✓）の動きは、説明のための演出です。

## 作り方

1. デモの会社のフォルダを戻す（リポの根で）：
   ```bash
   /usr/bin/python3 -B evals/_lib/fukugen.py 1件目を終えた <作業用の空のフォルダ>
   ```
2. 開いたときの hook を一度動かし、今の状態.html を作る（Claude で開くか、hooks/run.sh SessionStart を流す）。
3. 道具を入れる（初回だけ。docs/video で）：`npm install`（puppeteer-core と @xterm/xterm。この Mac の Google Chrome を使う）
4. PM の場面の端末を記録する（会社のフォルダは、作者の名前が入らない場所に置く。例 /tmp/やまぶき惣菜）：
   ```bash
   python3 docs/video/rec_terminal.py /tmp/やまぶき惣菜 <このリポ> docs/video/対話/pm_terminal.json "おはようございます。今日は何から手をつければいいですか？"
   ```
5. 組み立てる（リポの根で）：
   ```bash
   uv run --with numpy python docs/video/build.py <作業用のフォルダ> --provider vertex
   ```
   出来たものは `docs/video/out/hojokin_demo.mp4`。

旗：`--provider gemini|vertex|say`（声を作る先）、`--keep-voice`（out/voice/ の声をそのまま使う。人の声に差し替えるとき）、`--no-video`（映像を撮らない）、`--keep-video`（撮った映像を使い回し、音だけ重ね直す）。

声の鍵：`gemini` は環境変数 `GEMINI_API_KEY`（無ければ `HOJOKIN_TTS_ENV` の .env）。`vertex` は `gcloud auth login` 済みで、`HOJOKIN_TTS_PROJECT` に Google Cloud のプロジェクトを渡す。鍵はリポに置きません。

今の版の声は、Vertex AI の Gemini 3.8 Flash TTS（声 Charon）で作りました。耳で聴けないぶん、Gemini 2.5 Pro に書き起こさせて台本と照らし、読み違えた場面は台詞を言いやすく直して作り直しています。

ほかに要るもの：ffmpeg、LibreOffice（soffice）、pdftoppm（poppler）。

## ファイル

| ファイル | 中身 |
|---|---|
| 台詞.json | 場面ごとの台詞（text は字幕、speech は読み上げ用）と、台詞の後の間 |
| 素材.json | 動画に出す実物の文（対話の引用、整理した後の置き場、書き方の決まり、作り方の数） |
| 対話/ | 実際の対話・端末・hook の出力の記録 |
| video.html | 1コマを描くページ。`seek(t)` に秒を渡すと、その時刻の絵になる |
| build.py | 声 → 時刻表 → BGM → 映像 → 音を重ねる |
| tts.py | 台詞を声にする（本文だけを送る。1秒あたりの字数が外れたら作り直す） |
| rec_terminal.py | 本物の Claude Code を疑似端末で動かして記録する（作者の全体の設定は読まない） |
| make_bgm.py | BGM を numpy で作る（冒頭はマリンバの疎らな旋律、本編は D–A–Bm–G の明るい進行） |
| render.mjs | video.html を 30fps で撮って mp4 にする |
| stills.mjs | 確かめ用に、指定した秒の静止画を撮る |
