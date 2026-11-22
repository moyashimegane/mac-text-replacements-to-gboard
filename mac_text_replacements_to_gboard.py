#!/usr/bin/env python3
"""Macのテキストの置換（ユーザ辞書）を、Gboardの単語リストに取り込めるファイルに書き出す。

Macのユーザ辞書（~/Library/KeyboardServices/TextReplacements.db）を読み取り専用で読み、
全件をGboardの単語リストの形式（version:2）で dictionary.txt に書き出す。
書き出し先は、このファイルと同じフォルダにある config の out= か、--out で指定する。

使い方:
    ./mac_text_replacements_to_gboard.py
    ./mac_text_replacements_to_gboard.py --out ~/Desktop
"""

import argparse
import os
import sqlite3
import stat
import sys
import tempfile
from pathlib import Path

DEFAULT_DB = "~/Library/KeyboardServices/TextReplacements.db"
CONFIG_NAME = "config"
OUTPUT_NAME = "dictionary.txt"
LANGUAGE_TAG = "ja-JP"
HEADER = (
    "# Gboard Dictionary version:2\n"
    "# Gboard Dictionary format:shortcut\tword\tlanguage_tag\tpos_tag\n"
)
CONFIG_KEYS = ("out",)
FORBIDDEN_CHARS = ("\t", "\r", "\n")
# 消した印（ZWASDELETED）がNULLの行もあるので、NULLは消していない語として扱う
QUERY = (
    "SELECT ZSHORTCUT, ZPHRASE FROM ZTEXTREPLACEMENTENTRY "
    "WHERE ifnull(ZWASDELETED, 0) = 0"
)


class ToolError(Exception):
    """利用者に見せるエラー。"""


def default_config_path():
    """本体の実体（シンボリックリンクを辿った先）と同じフォルダのconfig。"""
    return Path(__file__).resolve().parent / CONFIG_NAME


def read_config(path):
    """configを読み、{キー: 値}を返す。

    UTF-8（BOMの有無は問わない）で読む。空行と#で始まる行は読み飛ばす。
    「キー=値」の形でない行、知らないキー、空の値、引用符で囲んだ値はエラーにする。
    """
    values = {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except UnicodeDecodeError as e:
        raise ToolError(f"configをUTF-8として読めません: {path}（UTF-8で保存し直してください）") from e
    except OSError as e:
        raise ToolError(f"configを読めません: {path}（{e.strerror}）") from e
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ToolError(f"{path}の{lineno}行目が「キー=値」の形になっていません")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in CONFIG_KEYS:
            raise ToolError(f"{path}の{lineno}行目のキー「{key}」は使えません（使えるのは out だけです）")
        if not value:
            raise ToolError(f"{path}の{lineno}行目の値が空です")
        if value[0] in "\"'":
            raise ToolError(f"{path}の{lineno}行目の値は引用符で囲まずに書いてください（空白もそのまま書きます）")
        values[key] = value
    return values


def resolve_output_dir(out_arg, config_path):
    """書き出し先のフォルダを決める。

    --out があれば config より優先する。config の out= は絶対パス（先頭の ~ は可）に限る。
    フォルダが無ければ作らずにエラーにする。
    """
    if out_arg is not None:
        if not out_arg:
            raise ToolError("--out の値が空です")
        out_dir = Path(os.path.expanduser(out_arg))
    elif config_path.is_file():
        out = read_config(config_path).get("out")
        if not out:
            raise ToolError(f"{config_path}に out= の行がありません")
        out_dir = Path(os.path.expanduser(out))
        if not out_dir.is_absolute():
            raise ToolError(f"{config_path}の out= は絶対パスで書いてください: {out}")
    else:
        example = config_path.with_name("config.example")
        raise ToolError(
            "出力先が決まっていません。"
            f"{example} を {config_path} という名前でコピーし、out= に出力先のフォルダを書いてください。"
            "一度だけ別の場所に出すときは --out <フォルダ> を付けます。"
        )
    if not out_dir.is_dir():
        raise ToolError(
            f"出力先のフォルダがありません: {out_dir}"
            "（自動では作りません。ネットワーク上のフォルダの場合は、つながっているかを確かめてください）"
        )
    return out_dir


def read_entries(db_arg):
    """辞書を読み取り専用で開き、消した語を除いた（読み, 語）の組の並びを返す。"""
    db = Path(os.path.expanduser(db_arg))
    if not db.is_file():
        raise ToolError(f"辞書のファイルがありません: {db}")
    # パスの ? # % 空白 をURIとして正しく変換するため、文字列を直接埋め込まない
    uri = db.resolve().as_uri() + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as e:
        raise ToolError(f"辞書を開けません: {db}（{e}）") from e
    try:
        return con.execute(QUERY).fetchall()
    except sqlite3.Error as e:
        raise ToolError(f"辞書を読めません: {db}（{e}）") from e
    finally:
        con.close()


def is_valid(value):
    """Gboardの1行に入れられる値か（空でなく、タブ・CR・LFを含まない文字列か）。"""
    return isinstance(value, str) and value != "" and not any(c in value for c in FORBIDDEN_CHARS)


def validate(rows):
    """（読み, 語）の組の並びを調べ、0件か、入れられない語が1つでもあればエラーにする。"""
    if not rows:
        raise ToolError("辞書に語が1件もありません。何も書き出していません。")
    bad = [(s, p) for s, p in rows if not (is_valid(s) and is_valid(p))]
    if bad:
        listed = "\n".join(f"  読み={s!r} 語={p!r}" for s, p in bad)
        raise ToolError(
            f"Gboardの形式に入れられない語が{len(bad)}件あります"
            "（読みか語が空、またはタブ・改行を含む）。"
            "Macのユーザ辞書で直してから実行してください。何も書き出していません。\n" + listed
        )


def build_text(rows):
    """（読み, 語）の組の並びから、ファイルの中身と件数を返す。

    同じ組は1つにまとめ、毎回同じ中身になるよう（読み, 語）の順に並べる。
    """
    pairs = sorted(set(rows))
    body = "".join(f"{s}\t{p}\t{LANGUAGE_TAG}\t\n" for s, p in pairs)
    return HEADER + body, len(pairs)


def current_umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


def write_atomic(out_dir, text):
    """一時ファイルに書いてから dictionary.txt へ名前を変え、書いたパスを返す。

    途中で失敗しても、書きかけの dictionary.txt や一時ファイルを残さない。
    既にある dictionary.txt の権限は引き継ぐ。新しく作るときは普通のファイルと同じ権限にする。
    """
    target = out_dir / OUTPUT_NAME
    try:
        fd, tmp = tempfile.mkstemp(prefix=".dictionary.", suffix=".tmp", dir=out_dir)
    except OSError as e:
        raise ToolError(f"書き出し先のフォルダに書き込めません: {out_dir}（{e.strerror}）") from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        # mkstempは0600で作るので、そのままだとネットワーク上のフォルダで別のユーザーから読めない。
        # 既にあるファイルの権限は、本人が絞っている場合があるので広げない。
        try:
            mode = stat.S_IMODE(os.stat(target).st_mode)
        except FileNotFoundError:
            mode = 0o666 & ~current_umask()
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return target


def main(argv=None, config_path=None):
    """コマンドの入口。終了コード（成功は0、エラーは1）を返す。

    config_path は、テストで config の場所を差し替えるためのもの。
    """
    parser = argparse.ArgumentParser(
        description="Macのテキストの置換（ユーザ辞書）を、Gboardの単語リストに取り込める dictionary.txt に書き出す。",
    )
    parser.add_argument("--out", help="出力先のフォルダ。configの out= より優先する")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"読む辞書のファイル（既定: {DEFAULT_DB}）")
    args = parser.parse_args(argv)
    if config_path is None:
        config_path = default_config_path()
    try:
        out_dir = resolve_output_dir(args.out, config_path)
        rows = read_entries(args.db)
        validate(rows)
        text, count = build_text(rows)
        target = write_atomic(out_dir, text)
    except ToolError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    print(f"{count}件を書き出しました: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
