#!/usr/bin/env python3
"""baseless.org のパワプロ選手データ（球団別HTML断片）から players.json を作る。

使い方:
  python3 tools/build_players.py H=/path/to/H.html T=/path/to/T.html ...
  （球団コード=ファイル。すでにある players.json に、指定した球団だけ追加・上書きする）

球団コード: T=阪神 BA=DeNA C=広島 D=中日 S=ヤクルト G=巨人 H=ソフトバンク F=日本ハム OBU=オリックス E=楽天 L=西武 M=ロッテ
"""
import sys, re, json, os
from html.parser import HTMLParser

TEAM_NAMES = {
    "T": "阪神タイガース", "BA": "横浜DeNAベイスターズ", "C": "広島東洋カープ", "D": "中日ドラゴンズ",
    "S": "東京ヤクルトスワローズ", "G": "読売ジャイアンツ", "H": "福岡ソフトバンクホークス",
    "F": "北海道日本ハムファイターズ", "OBU": "オリックス・バファローズ", "E": "東北楽天ゴールデンイーグルス",
    "L": "埼玉西武ライオンズ", "M": "千葉ロッテマリーンズ",
}


# <b>/<i>/<u> を入れ子の木にする（br と hr は葉として扱う）
class Node:
    def __init__(self, tag, attrs):
        self.tag = tag; self.attrs = dict(attrs); self.kids = []
    def text(self):
        return "".join(k if isinstance(k, str) else k.text() for k in self.kids).strip()

class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", []); self.stack = [self.root]
    def handle_starttag(self, tag, attrs):
        if tag in ("br", "hr"):
            self.stack[-1].kids.append(Node(tag, attrs)); return
        n = Node(tag, attrs); self.stack[-1].kids.append(n); self.stack.append(n)
    def handle_endtag(self, tag):
        if tag in ("br", "hr"): return
        if len(self.stack) > 1 and self.stack[-1].tag == tag: self.stack.pop()
        else:
            # 閉じタグの対応ずれに備えて探す
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i].tag == tag: del self.stack[i:]; break
    def handle_data(self, d):
        if d.strip(): self.stack[-1].kids.append(d)

def elems(n): return [k for k in n.kids if isinstance(k, Node) and k.tag not in ("br", "hr")]
def cls(n): return n.attrs.get("class", "").split()

def parse_file(path):
    p = P(); p.feed(open(path, encoding="utf-8").read())
    cards = [n for n in elems(p.root) if cls(n) and cls(n)[0] in ("p", "b")]
    return cards, p.root


POS = ["投", "捕", "一", "二", "三", "遊", "外"]


def items(group):
    """能力セルの並び。<b>/<i> の2要素 = 評価付き（b は青く強調、i は白）、<b>/<u> の文字だけ = 特殊能力（u は赤）"""
    out = []
    for k in elems(group):
        ch = elems(k)
        if len(ch) == 2:
            out.append({"n": ch[0].text(), "g": ch[1].text(), "hl": k.tag == "b"})
        elif not ch:
            t = k.text()
            if t:
                out.append({"n": t, "neg": k.tag == "u"})
    return out


def rows(group):
    """緑の特殊能力。<br> で行が分かれる。空の <b></b> は空きセル"""
    out, cur = [], []
    for k in group.kids:
        if isinstance(k, str):
            continue
        if k.tag == "br":
            out.append(cur); cur = []
        elif k.tag in ("b", "u", "i"):
            cur.append(k.text())
    out.append(cur)
    while out and not any(out[-1]):
        out.pop()
    return [[t for t in r] for r in out]


def basic(n):
    g = elems(n)
    info = [x.text() for x in elems(g[2])]
    stats = [x.text() for x in elems(g[3])]
    return g[0].text(), g[1].text(), info, stats


def role_of(n):
    main = "".join(k for k in n.kids if isinstance(k, str)).strip()
    sub = "".join(k.text() for k in n.kids if isinstance(k, Node)).strip()
    return {"main": main, "sub": sub}


def parse_card(c):
    kind = "P" if cls(c)[0] == "p" else "B"
    g = elems(c)
    name, num, info, stats = basic(g[0])
    d = {"name": name, "no": num, "kind": kind, "hand": info[0], "type": info[-1]}
    if kind == "P":
        d["form"] = info[1]
        d["season"] = stats[:5]  # 防御率 勝 敗 HP S
        pit = elems(g[1])
        d["velo"] = int(pit[0].text()); d["ctrl"] = int(pit[1].text()); d["stam"] = int(pit[2].text())
        q = {}
        for t in cls(c):
            if re.fullmatch(r"q\d{3}", t):
                q[int(t[1])] = (int(t[2]), int(t[3]))  # 枠ごとの変化量(1つ目, 2つ目)
        pitches = []
        slot = 0
        for it in elems(pit[3]):
            if it.tag == "i":
                if it.text():
                    pitches.append({"slot": slot, "n": it.text(), "amt": q.get(slot, (0, 0))[0], "second": False})
                slot += 1
            elif it.tag == "u" and re.fullmatch(r"s\d", (cls(it) or [""])[0]):
                sl = int(cls(it)[0][1])
                pitches.append({"slot": sl, "n": it.text(), "amt": q.get(sl, (0, 0))[1], "second": True})
        d["pitches"] = pitches
        d["role"] = role_of(pit[4])
        d["pg"] = items(g[3]); d["ps"] = items(g[4]); d["pt"] = rows(g[5])
        d["bg"] = items(g[6]); d["bs"] = items(g[7]); d["bt"] = rows(g[8])
        bat = elems(g[2])
    else:
        d["season"] = stats[:4]  # 打率 本塁打 打点 盗塁（推定）
        d["bg"] = items(g[2]); d["bs"] = items(g[3]); d["bt"] = rows(g[4])
        bat = elems(g[1])
    d["trj"] = int(bat[0].text()); d["meet"] = int(bat[1].text()); d["pow"] = int(bat[2].text())
    d["spd"] = int(bat[3].text()); d["arm"] = int(bat[4].text()); d["def"] = int(bat[5].text())
    slots = elems(bat[6])
    d["defpos"] = {POS[i]: int(s.text()) for i, s in enumerate(slots) if s.text()}
    d["catch"] = int(bat[7].text()); d["pos"] = bat[8].text()
    return d


def main(argv):
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "players.json")
    db = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
    for arg in argv:
        code, path = arg.split("=", 1)
        if code not in TEAM_NAMES:
            sys.exit("知らない球団コード: " + code)
        cards, _ = parse_file(path)
        rows = []
        for c in cards:
            d = parse_card(c)
            rows.append(d)
        db[TEAM_NAMES[code]] = rows
        print(code, TEAM_NAMES[code], len(rows), "人")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
    print("書き出し:", os.path.normpath(out), os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main(sys.argv[1:])
