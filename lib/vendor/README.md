# 同梱したライブラリ

会社のフォルダの版の履歴（`lib/history.py`）は、Python だけで動く Git の dulwich で扱います。
公式資料の PDF をページごとの文字にするところ（`lib/doc_text.py`。TASKS M2a）は、Python だけで動く pypdf で扱います。
財務モデル.xlsx を一から作るところ（`lib/zaimu_xlsx.py`。TASKS M5、DESIGN 8.3）は、Python だけで動く openpyxl で扱います。
どれも、ここに同梱しています。そのため、通信も venv の準備もなしに、`/usr/bin/python3`（3.9）で動きます。

- **通信できない場所で動かすため。** eval の中は、データの置き場が実行のたびに新しくなり、Bash から通信できません（experiments/E3/結果.md）。通信できないパソコンで初めて使うときも同じです。
- **初回に pip で入れていた形は、やめました。** 以前は、初回にプラグインのデータの置き場の venv に pip で入れていました（実験 E5）。この形だと、上の場所で道具が終了コード1で止まりました。

## 置いたもの

| ライブラリ | 版 | 取った所（PyPI の wheel） | wheel の sha256 | ライセンス | 大きさ |
|---|---|---|---|---|---|
| dulwich | 0.24.10 | `https://files.pythonhosted.org/packages/py3/d/dulwich/dulwich-0.24.10-py3-none-any.whl` | `15b32f8c3116a1c0a042dde8da96f65a607e263e860ee42b3d4a98ce2c2f4a06` | Apache-2.0 か GPL-2.0-or-later を選べる。このリポジトリでは **Apache-2.0** で使う | 2.4MB（.py が72個） |
| typing_extensions | 4.16.0 | `https://files.pythonhosted.org/packages/py3/t/typing_extensions/typing_extensions-4.16.0-py3-none-any.whl` | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` | PSF-2.0 | 164KB |
| pypdf | 6.21.4 | `https://files.pythonhosted.org/packages/3f/4b/77e8ad4ac42c9d93600f40541a50e9feb3a61d2bbee2d76f659346072051/pypdf-6.21.4-py3-none-any.whl` | `33e4fb41ca352810eb4e9838aa0d82d6888a5f8bf682f43e99cce5faa666255c` | BSD-3-Clause | 1.8MB（.py が59個） |
| openpyxl | 3.1.5 | `https://files.pythonhosted.org/packages/c0/da/977ded879c29cbd04de313843e76868e6e13408a94ed6b987245dc7c8506/openpyxl-3.1.5-py2.py3-none-any.whl` | `5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2` | MIT | 1.3MB（.py が190個） |
| et_xmlfile | 2.0.0 | `https://files.pythonhosted.org/packages/c1/8b/5fe2cc11fee489817272089c4203e679c63b570a5aaeb18d852ae3cbba6a/et_xmlfile-2.0.0-py3-none-any.whl` | `7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa` | MIT（標準のライブラリから写した部分は PSF） | 48KB（.py が3個） |

- **typing_extensions を入れた理由。** dulwich は Python 3.11 より前では、読み込むときに typing_extensions を使います。pypdf も同じです。
- **pypdf を入れた理由。** 公式資料の PDF を、ページごとの文字にするためです（DESIGN 9.2）。C の拡張を持つもの（pdfminer の速くする版、pypdfium2 など）は使いません。
  - 要る物は typing_extensions だけです（Python 3.11 より前）。暗号の機能（cryptography など）と画像の機能（Pillow）は、追加の指定（extra）のときだけ要るので入れません。公式資料は暗号のかかっていない PDF で、文字だけを取り出します。
  - wheel の sha256 は、PyPI の JSON（`https://pypi.org/pypi/pypdf/6.21.4/json`）の値と、取った wheel から出した値が同じことを確かめました（2026-11-04）。
- **openpyxl を入れた理由。** 財務モデル.xlsx のように、ツールが一から作る Excel を書くためです（DESIGN 8.3、実験 E2b）。
  - 公式の様式（その3 など）は openpyxl で開いて保存しません。拡張の条件付き書式・入力規則の一覧・図形などが落ちるためです（実験 E2b。様式は XML を直接書き換える。TASKS M6）。
  - 要る物は et_xmlfile だけです。lxml（C の拡張）・numpy・Pillow・defusedxml は、あれば使い、なくても動く作りなので入れません。
  - wheel の sha256 は、PyPI の JSON（`https://pypi.org/pypi/openpyxl/3.1.5/json`、`https://pypi.org/pypi/et-xmlfile/2.0.0/json`）の値と、取った wheel から出した値が同じことを確かめました（2026-11-04）。
  - どちらも `Requires-Python: >=3.8` なので、`/usr/bin/python3`（3.9）で動きます。
- **ライセンスの全文。**
  - dulwich は `dulwich-0.24.10.dist-info/licenses/COPYING` にあります。2つのライセンスの本文が入っています。
  - typing_extensions は `typing_extensions-4.16.0.dist-info/licenses/LICENSE` にあります。
  - pypdf は `pypdf-6.21.4.dist-info/licenses/LICENSE` にあります。
  - openpyxl は `openpyxl-3.1.5.dist-info/LICENCE.rst` にあります（dist-info の直下）。
  - et_xmlfile は `et_xmlfile-2.0.0.dist-info/` の直下に、`LICENCE.rst`（MIT）、`LICENCE.python`（標準のライブラリから写した部分の PSF のライセンス）、`AUTHORS.txt` があります。
  - どの wheel にも NOTICE のファイルはありません。

## 置き方の決まり

- **中身は変えない。** wheel の中身（`dulwich/`、`typing_extensions.py`、`pypdf/`、`openpyxl/`、`et_xmlfile/`）を、1バイトも変えずに置きます。
  - `tests/test_vendor.py` が、wheel の RECORD のハッシュと照らして確かめます。
- **dist-info は一部だけ置く。** 置くのは METADATA・RECORD・WHEEL と、ライセンスの全文（licenses/ の下、または dist-info の直下の LICENCE.*・AUTHORS.txt）だけです。
  - コマンドの入口（`dulwich-0.24.10.data/scripts/`、entry_points.txt）と top_level.txt は置きません。
- **C の拡張は入れない。** どれも Python だけの wheel（py3-none-any。openpyxl は py2.py3-none-any）です。
  - dulwich は、速くする拡張がないと、Python だけの処理で動きます。
- **urllib3 は入れない。** dulwich の要る物に urllib3 があります。ただ、読み込むのは HTTP で送る・取ってくるときと、型を確かめるときだけです。
  - 版の履歴の操作（作る・加える・残す・変わったファイルを見る）では、読み込みません。
  - 送る機能は使いません（DESIGN 5章「履歴を外に送らない」）。

## 読み込み方

- `lib/history.py` が、このフォルダを `sys.path` の先頭に入れてから、dulwich を読み込みます。
  - 先頭に入れるのは、社長のパソコンに別の版の dulwich が入っていても、同梱の版を使うためです。
- `lib/zaimu_xlsx.py` も同じ形で、同梱の openpyxl を読み込みます。
  - テストの Python（uv が入れた新しい版）の中では読み込みません。読み込むと、このフォルダに `__pycache__` ができるためです。テストは `/usr/bin/python3 -B` で動かします。
- スクリプトは `python3 -B` で動かします。プラグインの場所に `__pycache__` を書かないためです。

## 版を上げるとき

1. PyPI から、Python だけの wheel（`py3-none-any`）を取ります。sha256 が PyPI の値と同じかを確かめます。
2. Python 3.9 で動く版を選びます（`Requires-Python`）。
3. 上と同じ形で置き換え、この表を直します。
4. `uv run pytest tests/test_vendor.py tests/test_T0_8.py tests/test_company_init.py tests/test_T3_1.py` を流します。
