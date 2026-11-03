# e1-probe（実験 E1 の試しのプラグイン）

デスクトップアプリの内蔵ブラウザと Claude in Chrome の道具の呼び出しを、hook が受け取れるかを確かめるための試しのプラグインです。

- PreToolUse・PostToolUse：名前に `Claude_Browser`・`claude-in-chrome`・`computer-use` を含む道具の、入力と結果を `~/.hojokin-e1/hooks.jsonl` に書く。
- 拒む試し：入力の値に「拒否テスト」を含む操作と、ダブルクリックを拒む（理由の合言葉：くすのき2）。
- UserPromptSubmit：送られた文を記録し、`/e1-probe:nyuryoku` を見分けたら「画面入力の許可」の控えを作る（E1b）。
- skill `nyuryoku`：担当者だけが呼べる（`disable-model-invocation: true`）。

hook は目印（`.hojokin/`）のあるフォルダでだけ動きます。手順は `experiments/E1/手順.md` にあります。
