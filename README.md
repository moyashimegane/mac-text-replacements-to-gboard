# mac-text-replacements-to-gboard

Macの「テキストの置換」（日本語の画面では「ユーザ辞書」）を、AndroidのGboardの単語リストに取り込めるファイル`dictionary.txt`に書き出すスクリプトです。

## 何をするか

- Macのユーザ辞書の実体（`~/Library/KeyboardServices/TextReplacements.db`）を、読み取り専用で直接読みます。システム設定から一覧をドラッグして書き出す必要はありません。
- 全件を、Gboardの単語リストの形式で`dictionary.txt`に書き出します。
- Gboardへのインポートは、手で行います。Gboardには、外のアプリから単語リストに取り込む手段がありません。

## 動く条件

- macOS
- Python 3（3.15で確認）。標準ライブラリだけを使います。

## 準備

1. このリポジトリをcloneします。
2. 書き出し先のフォルダを作っておきます。スクリプトはフォルダを作りません。
3. `config.example`を`config`という名前で写し、`out=`に書き出し先のフォルダを絶対パスで書きます。`config`はgitの管理から外してあります。

```sh
cp config.example config
```

```text
out=/Volumes/NAS/share/gboard-import
```

## 使い方

```sh
./mac_text_replacements_to_gboard.py
```

`config`の`out=`のフォルダに`dictionary.txt`を書き出します。同じ名前のファイルがあれば上書きします。

```text
341件を書き出しました: /Volumes/NAS/share/gboard-import/dictionary.txt
```

一度だけ別のフォルダに書き出すときは、`--out`を付けます。`config`より優先します。

```sh
./mac_text_replacements_to_gboard.py --out ~/Desktop
```

## Gboardへのインポート

1. `dictionary.txt`を、Androidの端末に入れます（NASのアプリ、Googleドライブなど）。
2. Gboardの設定→「単語リスト」→「単語リスト」→「日本語」→右上のメニュー→「インポート」と進み、`dictionary.txt`を選びます。NASなどのネットワークのボリュームに書き出すと、macOSが同じフォルダに`._dictionary.txt`という小さなファイルを作ることがあります。それではない方を選びます。

Gboard 18.6.7（Android 17）で確認しました。

## 知っておくこと

- 毎回、全件を書き出します。同じ読みと語の組は、何度インポートしてもGboardの中で二重になりません。そのため、全件をそのままインポートして構いません。
- インポートは追加だけです。Macで消した語や、直す前の語は、Gboardに残ります。消したいときは、Gboardの単語リストで手で消します。
- 書き出す形式は、Gboard自身の書き出しと同じです。
  - 1行目：`# Gboard Dictionary version:2`
  - 2行目：`# Gboard Dictionary format:shortcut<TAB>word<TAB>language_tag<TAB>pos_tag`
  - 3行目から：`読み<TAB>語<TAB>ja-JP<TAB>`（品詞の欄は空）
  - UTF-8（BOMなし）、改行はLFです。品詞の欄が空の語も、変換の候補に出ます。
- iCloudでiPhoneのユーザ辞書と同期している場合は、iPhoneで足した語も入ります。
- 読みか語が空の語、タブや改行を含む語が1つでもあると、何も書き出さずに止まります。Macのユーザ辞書で直してから実行してください。
- 書き出し先のフォルダが無いと止まります。Finderなどでつないだネットワークのボリューム（`/Volumes/...`）は、外すとフォルダごと消えるので、つながっていないときも止まります。自分で作ったフォルダにNASをマウントしている場合は、外れても空のフォルダが残るので止まりません。
- `TextReplacements.db`は、Appleが公開している形式ではありません。macOS 27.2で確認しましたが、macOSの更新で変わる可能性があります。
- `dictionary.txt`の中身は、自分の辞書そのものです。公開の場所に置かないでください。

## テスト

```sh
python3 -m unittest discover -s tests
```

## ライセンス

[MIT](./LICENSE)
