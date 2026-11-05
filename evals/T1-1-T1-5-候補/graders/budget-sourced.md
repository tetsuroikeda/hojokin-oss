---
type: regex
target:
  source: file
  path: 記録/一時/補助金の候補.json
pattern: '"予算の状況":\s*(?!\[[^\]]*(https?://|見つからなかった))(?!"[^"]*(https?://|見つからなかった))[\["]'
match: not_contains
---

T1-5：すべての候補の予算の状況に、出典の URL か「見つからなかった」がある（推測で書かない）。
