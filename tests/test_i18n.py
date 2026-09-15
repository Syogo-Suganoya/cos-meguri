"""画面の英語訳の漏れを見張る。

訳の鍵は日本語の原文（web/js/core/i18n.js）。HTML の印と JS の t("…") から鍵を集め、
web/js/core/en.js にすべて訳があるかを見る。訳が無くても画面は日本語に落ちるだけで壊れないので、
ここで声を出させないと、英語の画面に日本語が混ざったまま気づかない。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
HTML_FILES = [WEB / "index.html", *sorted((WEB / "pages").glob("*.html"))]
# en.js は訳そのもの、i18n.js は仕組み。どちらも t() の呼び出し元ではない
JS_FILES = sorted(p for p in (WEB / "js").rglob("*.js") if p.name not in {"en.js", "i18n.js"})

JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def _english_keys() -> dict[str, str]:
    source = (WEB / "js" / "core" / "en.js").read_text()
    pairs = re.findall(r'^\s*"((?:[^"\\]|\\.)*)":\s*\n?\s*"((?:[^"\\]|\\.)*)"', source, flags=re.M)
    return {key: value for key, value in pairs}


def _html_keys(path: Path) -> set[str]:
    html = path.read_text()
    return set(re.findall(r'data-i18n(?:-html|-placeholder|-aria-label)?="([^"]+)"', html))


def _t_call_literals(source: str) -> set[str]:
    """t( … ) の引数に直接書かれた文字列（三項演算子の両側も）を集める。"""
    found: set[str] = set()
    for match in re.finditer(r"(?<![\w.$])t\(", source):
        depth, i = 1, match.end()
        while i < len(source) and depth:
            ch = source[i]
            if ch == '"':
                end = i + 1
                while source[end] != '"':
                    end += 2 if source[end] == "\\" else 1
                # 鍵はすべて日本語の原文。`kind === "makeup"` のような比較の文字列は拾わない
                if depth == 1 and JAPANESE.search(source[i + 1 : end]):
                    found.add(source[i + 1 : end])
                i = end
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
    return found


def _js_keys(path: Path) -> set[str]:
    source = path.read_text()
    keys = _t_call_literals(source)
    # 変数を通して t() に渡す文言（誤りの印の言い換え・帯の節の名前）
    if path.name == "api.js":
        block = source.split("const ERROR_CODES", 1)[1].split("};", 1)[0]
        keys |= set(re.findall(r':\s*"([^"]+)"', block))
    if path.name == "shell.js":
        keys |= set(re.findall(r'label: "([^"]+)"', source))
    return keys


@pytest.mark.parametrize("path", HTML_FILES + JS_FILES, ids=lambda p: p.name)
def test_every_marked_text_has_an_english_translation(path):
    keys = _html_keys(path) if path.suffix == ".html" else _js_keys(path)
    missing = sorted(key for key in keys if key not in _english_keys())
    assert not missing, f"{path.name} の訳が en.js に無い: {missing}"


# 駅名の例だけは日本語の表記も見せる（駅すぱあとは日本語の駅名がいちばん確実に引ける）
STATION_EXAMPLES = {"例: 国際展示場", "例: 横浜"}


def test_translations_are_actually_english():
    leaking = {
        k: v for k, v in _english_keys().items() if JAPANESE.search(v) and k not in STATION_EXAMPLES
    }
    assert not leaking, leaking


def test_the_dictionary_was_read():
    """鍵の読み取りが壊れて 0 件になると、上のテストが黙って通る。"""
    assert len(_english_keys()) > 100


@pytest.mark.parametrize("path", HTML_FILES, ids=lambda p: p.name)
def test_no_japanese_text_is_left_unmarked_in_html(path):
    """印の無い日本語は英語の画面にそのまま残る。コメントと印の付いた要素を除いて、日本語が無いこと。"""
    html = path.read_text()
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
    # 印の付いた要素は中身ごと外す（入れ子の無い要素に付けている）
    html = re.sub(
        r"<(\w+)\b[^>]*data-i18n(?:-html)?=\"[^\"]*\"[^>]*>.*?</\1>", "", html, flags=re.S
    )
    # 属性（aria-label・placeholder）は data-i18n-* を併記していれば訳される
    html = re.sub(r'\s(?:aria-label|placeholder)="[^"]*"(?=[^>]*data-i18n-(?:aria-label|placeholder)=)', "", html)
    html = re.sub(r'\sdata-i18n-[\w-]+="[^"]*"', "", html)
    leftover = [line.strip() for line in html.splitlines() if JAPANESE.search(line)]
    assert not leftover, f"{path.name} に訳の印が無い日本語: {leftover}"


@pytest.mark.parametrize("path", HTML_FILES, ids=lambda p: p.name)
def test_english_readers_do_not_see_a_flash_of_japanese(path):
    """英語の人には訳し終えるまで本文を隠す。外し忘れても白いままにならないよう、時限で外す。"""
    head = path.read_text().split("</head>", 1)[0]
    assert "i18n-pending" in head and "setTimeout" in head, path.name
