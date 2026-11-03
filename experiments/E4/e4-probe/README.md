# e4-probe（実験 E4 の試しのプラグイン）

デスクトップアプリの Code タブで、プラグインの hook が動くかを確かめるための試しのプラグインです。
SessionStart・UserPromptSubmit・PreToolUse・Stop の4つの場面で、受け取った情報を `~/.hojokin-e4/hooks.jsonl` に書きます。
起動用の `run.sh` は、python より前に PATH や python の版を `~/.hojokin-e4/sh.log` に書きます。

目印（`.hojokin/`）のあるフォルダでだけ、次の試しをします。

- SessionStart：合言葉を、開いたときの情報として Claude に渡す
- PreToolUse：`E4_DENY_JSON` を含む Bash を JSON で拒み、`E4_DENY_EXIT2` を含む Bash を終了コード2で拒む。名前に `_v2` を含む Write も拒む
- Stop：`E4_STOP_TEST` と送った応答の終わりに、1回だけ差し戻す

目印のないフォルダでは、場面・cwd・道具の名前だけを書き、何も止めません。手順は `experiments/E4/手順.md` にあります。
