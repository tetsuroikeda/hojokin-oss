---
type: regex
target:
  source: file
  path: 今の状態.html
pattern: '<td>金融機関確認書</td><td>[^<]*</td><td>依頼した</td><td>頼む：社長'
---

今の状態の画面の「外部への依頼と待ち」の一覧に、確認書の状態（依頼した）と、だれがするか（頼む：社長）が出たか（SPEC T6-6「だれがするかが一覧に出る」）。
