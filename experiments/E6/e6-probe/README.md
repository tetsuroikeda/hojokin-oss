# e6-probe（実験 E6 の試しのプラグイン）

デスクトップアプリの Code タブで、会社のフォルダの `.claude/settings.json`（DESIGN 4.7）が効くかを確かめるための試しのプラグインです。

- skill `junbi`：会社のフォルダの目印と `.claude/settings.json` を、スクリプトで作る（作ったその場で効くかを見る）
- skill `torikomi`：社長が伝えた外の場所のファイルを、スクリプトで会社のフォルダに写す（allowed-tools で確認なしに動くかを見る）
- skill `yomu`：プラグインの中の補助ファイルを Read で読む（外を読ませない設定のもとで読めるかを見る）
- hook：PreToolUse は道具の呼び出しを記録するだけ。Stop は、原本が台帳のハッシュと違えば Git の履歴から戻し、1回だけ Claude に知らせる

hook は目印（`.hojokin/`）のあるフォルダでだけ動き、記録は `~/.hojokin-e6/hooks.jsonl` に書きます。手順は `experiments/E6/手順.md` にあります。
