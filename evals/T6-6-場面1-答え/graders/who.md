---
type: regex
target:
  source: file
  path: 記録/期限の台帳.json
pattern: '"書類": "金融機関確認書"[^}]{0,400}"頼む人": "社長"'
---

だれが頼むか（社長。A3）を、期限の台帳に残したか（SPEC T6-6「だれがするかが一覧に出る」）。
