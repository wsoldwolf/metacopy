# metacopy

PNG / WebP 画像に埋め込まれた ComfyUI の `prompt` と `workflow` を、別の既存画像へ複製する Python スクリプトです。Python の標準ライブラリのみで動作し、追加パッケージのインストールは不要です。

## 動作環境

- Python 3（動作確認: Python 3.13）
- Windows 用の起動ファイル `metacopy.cmd` を同梱

## 使い方

`metacopy.py` があるフォルダーで実行します。

```powershell
python metacopy.py from.webp to.webp
```

Windows の PowerShell では、付属の起動ファイルでも実行できます。

```powershell
.\metacopy from.webp to.webp
```

このフォルダーを `PATH` に追加している場合は、次のように実行できます。

```text
metacopy from.webp to.webp
```

第1引数はコピー元、第2引数はコピー先です。**両方のファイルが存在している必要があります。コピー先を上書きします。** コピー元は変更しません。同じファイルをコピー元・コピー先に指定することはできません。

パスに空白が含まれる場合は引用符で囲みます。

```powershell
python metacopy.py "images/source image.png" "images/target image.webp"
```

ヘルプ:

```powershell
python metacopy.py --help
```

## 対応形式

| コピー元 | コピー先 |
| --- | --- |
| PNG | PNG |
| PNG | WebP |
| WebP | PNG |
| WebP | WebP |

形式は拡張子ではなく、ファイルの内容から判定します。画像形式そのものの変換は行いません。

## コピーする内容

- `prompt`: ComfyUI の実行用プロンプト JSON
- `workflow`: ComfyUI のワークフロー JSON

コピー先にある既存の `prompt` / `workflow` を取り除き、コピー元に存在する項目を設定します。たとえば、コピー元に `prompt` しかない場合、コピー先の既存の `workflow` は削除されます。

画像の圧縮データをそのまま保持するため、再圧縮による画質劣化はありません。コピー対象以外のコピー先のチャンクや EXIF タグは保持します。コピー元のその他のメタデータは複製しません。

### メタデータの格納形式

- PNG: `tEXt` / `zTXt` / `iTXt` の `prompt` / `workflow` を読み取り、`tEXt` として書き込みます。
- WebP: EXIF の最初の IFD にある ASCII 型文字列のうち、`prompt:` / `workflow:` で始まる値を読み取ります。書き込み先は Model（`0x0110`）と Make（`0x010F`）です。
- 値は有効な JSON である必要があります。PNG への書き込みでは、JSON の空白や Unicode の表記が変わることがありますが、JSON としての内容は保持します。

カスタムノード独自の格納方式（XMP や EXIF UserComment など）は対象外です。

## 書き込みとエラー

出力データをメモリ上で作成してメタデータを検証した後、コピー先と同じフォルダーに一時ファイルを書き込み、置換します。コピー先フォルダーにも書き込み権限が必要です。バックアップファイルは作成しません。

主なエラー条件:

- コピー元またはコピー先が存在しない。
- コピー元とコピー先が同じファイル。
- PNG / WebP 以外、または検出可能な構造の破損がある。
- コピー元に `prompt` / `workflow` がない、または値が有効な JSON ではない。
- コピー先 WebP に複数の EXIF チャンクがある。
- 書き込みに必要な EXIF Make / Model タグが、無関係な情報に使われている。

成功時はコピーしたキーとコピー先を表示します。

```text
Copied prompt, workflow -> to.webp
```

終了コードは成功時 `0`、処理エラー時 `1`、引数の指定エラー時 `2` です。処理エラーは標準エラー出力に `metacopy: ...` と表示されます。

ファイル全体をメモリに読み込むため、大きな画像やアニメーションを扱う際は、ファイルサイズに応じたメモリが必要です。

## テスト

```powershell
python -m unittest -v
```

形式間の4通りのコピー、画像圧縮データの保持、日本語・絵文字、コピー先が存在しない場合、圧縮 PNG テキスト、EXIF のバイト順と既存タグの保持を確認します。WebP はコンテナー構造用のテストデータを使用しており、画像デコーダーや ComfyUI の画面での検証は含みません。

## ファイル構成

| ファイル | 用途 |
| --- | --- |
| `metacopy.py` | スクリプト本体 |
| `metacopy.cmd` | Windows 用起動ファイル（`python` が PATH に必要） |
| `test_metacopy.py` | 標準ライブラリの unittest によるテスト |

## ライセンス

このプロジェクトは GNU General Public License version 3（GPL-3.0-only）の下で提供されます。ライセンス全文は [LICENSE](LICENSE) を参照してください。
