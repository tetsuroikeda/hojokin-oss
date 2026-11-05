---
type: regex
target:
  source: file
  path: 記録/質問の記録.json
pattern: '"案件": "[^"]*",\s*"段階": "[^"]*"'
---

T0-11：質問の記録に、案件と段階の欄が付いている（探す段階では案件がまだないので、値は hook の決め方による）。
