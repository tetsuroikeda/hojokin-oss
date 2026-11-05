---
type: regex
target:
  source: file
  path: 記録/経費明細.json
pattern: '"原本": "[^"]*(ほしみ|概算|2026-10-06)'
match: not_contains
---

相見積（ほしみ機工）と、置き換わって期限も切れた概算（つばさ台 10/6）の金額を、経費明細に入れていないか。
