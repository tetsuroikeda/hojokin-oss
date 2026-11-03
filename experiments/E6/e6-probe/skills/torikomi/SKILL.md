---
name: torikomi
description: 実験 E6 の試し。社長が伝えた外の場所のファイルを、スクリプトで会社のフォルダの「取り込み」に写す。
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/torikomi.py *)
---

# 外のファイルを取り込む

社長が伝えた場所を `<場所>` に入れて、次のコマンドを、形を変えずにそのまま1回で実行してください（前に `cd` などを付けない。場所を自分で確かめるために、ほかの道具で先に読まない）。

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/torikomi.py <場所>
```

実行したら、スクリプトの出力をそのまま報告してください。
