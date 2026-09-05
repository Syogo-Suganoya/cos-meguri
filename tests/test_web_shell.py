"""ページ・ルート・Service Worker の三すくみを見張る。

HTML／main.py のルート／sw.js の SHELL は、どれか1つが欠けると
「オフラインのときだけ404」のような見えない壊れ方をする。ここで声を出させる。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"

# URL → HTML ファイル。main.py の PAGES と対になる
PAGES = {
    "/": WEB / "index.html",
    "/prep": WEB / "pages" / "prep.html",
    "/plan": WEB / "pages" / "plan.html",
    "/looks": WEB / "pages" / "looks.html",
    "/day": WEB / "pages" / "day.html",
}

# 左端のシェブロンの節。shell.js の STEPS と対になる
STEPS = ["prep", "plan", "looks", "day"]


@pytest.mark.parametrize("url,path", PAGES.items())
def test_every_page_is_served(client, url, path):
    assert path.is_file(), f"{path} がない"
    res = client.get(url)
    assert res.status_code == 200
    assert res.text.lstrip().startswith("<!DOCTYPE html>")


@pytest.mark.parametrize("url,path", PAGES.items())
def test_every_page_declares_its_own_body_class_and_module(url, path):
    """ページごとの色と初期化は body クラスと専用モジュールで決まる。"""
    html = path.read_text()
    assert re.search(r'<body class="p-[a-z]+"', html), f"{path.name} に body クラスがない"
    modules = re.findall(
        r'<script type="module" src="(/static/js/pages/[a-z]+\.js)(?:\?v=\d+)?"', html
    )
    assert len(modules) == 1, f"{path.name} のページモジュールは1本だけにする"


def test_shell_steps_match_this_test(client):
    """シェブロンの節が増減したら、このテストも直させる。"""
    shell = (WEB / "js" / "core" / "shell.js").read_text()
    assert re.findall(r'key: "([a-z]+)"', shell) == STEPS


@pytest.mark.parametrize("path", PAGES.values())
def test_referenced_static_assets_exist(path):
    html = path.read_text()
    for ref in re.findall(r'(?:src|href)="(/static/[^"?]+)', html):
        assert (WEB / ref[len("/static/") :]).is_file(), f"{path.name} が参照する {ref} がない"


def test_no_inline_onclick_survives_the_module_split():
    """module スコープの関数は onclick 属性から呼べない。呼んでも無言で何も起きない。"""
    for js in WEB.rglob("*.js"):
        assert "onclick=" not in js.read_text(), f"{js.name} に onclick 属性が残っている"
    for html in PAGES.values():
        assert "onclick=" not in html.read_text(), f"{html.name} に onclick 属性が残っている"


PAGE_MODULES = sorted((WEB / "js" / "pages").glob("*.js"))


@pytest.mark.parametrize("js", PAGE_MODULES, ids=lambda p: p.name)
def test_first_paint_comes_after_the_const_declarations(js):
    """モジュールの直下で、あとから宣言する const を掴む関数を呼ばない。

    `const` は巻き上がっても初期化されない（TDZ）。描画の呼び出しを
    ファイルの先頭に置くと、下で宣言したテンプレート関数に触れた瞬間
    ReferenceError で止まり、画面だけが白くなる。3回踏んだので見張る。
    """
    lines = js.read_text().splitlines()
    local_fns = {m.group(1) for line in lines if (m := re.match(r"function (\w+)", line))}
    if not local_fns:
        return

    # 字下げの無い行だけがモジュール直下。関数の中身は対象にしない
    consts = [i for i, line in enumerate(lines) if re.match(r"const \w+ =", line)]
    calls = [
        i
        for i, line in enumerate(lines)
        if (m := re.match(r"(?:await )?(\w+)\(", line)) and m.group(1) in local_fns
    ]
    if not consts or not calls:
        return

    assert min(calls) > max(consts), (
        f"{js.name}: {lines[min(calls)].strip()} が "
        f"{lines[max(consts)].strip()} より前にある。呼び出しをファイルの末尾へ移す"
    )


@pytest.mark.parametrize("url,path", PAGES.items())
def test_every_page_declares_its_icons(client, url, path):
    """印が無いとタブでどれがコスめぐりか分からない。iOS は PNG しか受けない。"""
    html = path.read_text()
    for rel, href in (("icon", "/favicon.svg"), ("apple-touch-icon", "/apple-touch-icon.png")):
        assert f'rel="{rel}" href="{href}"' in html, f"{path.name} に {rel} がない"
        assert client.get(href).status_code == 200, f"{href} が引けない"


def test_manifest_icons_all_resolve(client):
    manifest = json.loads((WEB / "manifest.webmanifest").read_text())
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200, f"manifest の {icon['src']} が引けない"


def test_service_worker_caches_the_stylesheet_the_pages_actually_ask_for():
    """SHELL の ?v= がページとずれると、その1本だけ黙って先読みされなくなる。"""
    sw = (WEB / "sw.js").read_text()
    cached = set(re.findall(r'"/static/(style\.css\?v=\d+)"', sw))
    asked = {
        m for html in PAGES.values() for m in re.findall(r'/static/(style\.css\?v=\d+)"', html.read_text())
    }
    assert cached == asked, f"sw.js は {cached}、ページは {asked} を見ている"


def test_service_worker_shell_is_all_reachable(client):
    """SHELL に404が1つでも混じると、オフラインの備えが黙って消える。"""
    sw = (WEB / "sw.js").read_text()
    urls = re.findall(r'"(/[^"]*)"', sw.split("const SHELL")[1].split("];")[0])
    assert urls, "SHELL を読み取れなかった"
    for url in urls:
        assert client.get(url).status_code == 200, f"SHELL の {url} が引けない"


def test_page_route_does_not_shadow_the_api_or_docs(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/api/events").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/nope").status_code == 404
