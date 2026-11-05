---
type: regex
pattern: 'git log|git checkout|git revert|git reset|ターミナル|コミット'
match: not_contains
---

社長に Git の操作（コマンド、コミットなど）を求めていないか（SPEC T0-9「Git の操作を求めずに」、台本の「出ない文字」）。
