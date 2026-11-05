---
type: regex
target:
  source: file
  path: 記録/一時/補助金の候補.json
pattern: '"名前":\s*"[^"]*助成金[^"]*",(?:(?!"名前")[\s\S])*?https://www\.mhlw\.go\.jp/'
---

T1-1：厚生労働省の助成金が1つ以上入る（名前に「助成金」があり、同じ候補の中に厚生労働省のサイトの URL がある）。
