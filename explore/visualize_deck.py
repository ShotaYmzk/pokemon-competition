"""デッキ(agent/deck.csv)を画像付きHTMLレポートとして可視化する。

使い方:
    source env/venv311/bin/activate
    python explore/visualize_deck.py [--deck agent/deck.csv] [--out explore/deck_visualization]

JP_Card_Data.csv からカード名・種類などを引き、
Card_ID List_JP.pdf から該当カードのカード画像を抜き出して
グループ分けされたHTMLレポートと、確認用の一覧PNGを生成する。
"""
import argparse
import base64
import csv
import io
from collections import Counter, defaultdict
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
CARD_DATA_CSV = ROOT / "pokemon-tcg-ai-battle" / "JP_Card_Data.csv"
CARD_PDF = ROOT / "pokemon-tcg-ai-battle" / "Card_ID List_JP.pdf"

STAGE_FIELD = "ポケモンの進化の段階/エネルギー・トレーナーズの種類"
STAGE_ORDER = [
    "ポケモン/たね",
    "ポケモン/1進化",
    "ポケモン/2進化",
    "ポケモンのどうぐ",
    "グッズ",
    "サポート",
    "スタジアム",
    "特殊エネルギー",
    "基本エネルギー",
]


def load_card_data():
    with open(CARD_DATA_CSV, encoding="utf-8") as f:
        return {row["カード ID"]: row for row in csv.DictReader(f)}


def load_deck(deck_path):
    with open(deck_path, encoding="utf-8") as f:
        ids = [line.strip() for line in f if line.strip()]
    return Counter(ids)


def build_id_to_page_map(doc):
    """カード一覧の表ページを走査し、カードID -> 券面画像のページ番号 を作る。"""
    import re

    mapping = {}
    for i in range(len(doc)):
        text = doc[i].get_text()
        ids = re.findall(r"(?m)^(\d+)$", text)
        links = sorted(doc[i].get_links(), key=lambda l: l["from"].y0)
        if not ids or len(ids) != len(links):
            # 表ページの並びが終わったら走査を終了する
            break
        for cid, link in zip(ids, links):
            mapping[cid] = link["page"]
    return mapping


def render_card_image(doc, page_index, dpi=150):
    page = doc[page_index]
    infos = page.get_image_info()
    pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(*infos[0]["bbox"]) if infos else None)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def to_data_uri(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deck", default=str(ROOT / "agent" / "deck.csv"))
    parser.add_argument("--out", default=str(ROOT / "explore" / "deck_visualization"))
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    card_data = load_card_data()
    deck_counts = load_deck(args.deck)
    total = sum(deck_counts.values())

    doc = fitz.open(str(CARD_PDF))
    id_to_page = build_id_to_page_map(doc)

    # カードを進化段階/種類でグループ化
    groups = defaultdict(list)
    unknown_ids = []
    for cid, count in deck_counts.items():
        row = card_data.get(cid)
        if row is None:
            unknown_ids.append(cid)
            continue
        stage = row[STAGE_FIELD]
        groups[stage].append((cid, count, row))

    # 違反チェック(枚数60枚、同名4枚以下、基本エネルギーは例外)
    name_counts = Counter()
    for cid, count, row in (item for items in groups.values() for item in items):
        if row["カテゴリ"] != "基本エネルギー" and row[STAGE_FIELD] != "基本エネルギー":
            name_counts[row["カード名"]] += count
    over_limit = {name: c for name, c in name_counts.items() if c > 4}

    images = {}
    for cid in deck_counts:
        page_index = id_to_page.get(cid)
        if page_index is None:
            continue
        img = render_card_image(doc, page_index)
        img.thumbnail((300, 420))
        images[cid] = img

    # ---- HTML レポート ----
    html_parts = [
        "<html><head><meta charset='utf-8'><title>デッキ一覧</title><style>",
        "body{font-family:sans-serif;background:#222;color:#eee;}",
        "h1{color:#fff;} h2{border-bottom:2px solid #888;padding-bottom:4px;margin-top:40px;}",
        ".grid{display:flex;flex-wrap:wrap;gap:16px;}",
        ".card{background:#333;border-radius:8px;padding:8px;width:160px;text-align:center;}",
        ".card img{width:100%;border-radius:6px;}",
        ".count{font-size:20px;font-weight:bold;color:#ffd54f;}",
        ".name{font-size:13px;margin-top:4px;}",
        ".warn{color:#ff5252;font-weight:bold;}",
        ".ok{color:#69f0ae;font-weight:bold;}",
        "</style></head><body>",
        f"<h1>デッキ一覧（合計 {total} 枚）</h1>",
    ]
    if total == 60:
        html_parts.append("<p class='ok'>枚数チェック: OK (60枚)</p>")
    else:
        html_parts.append(f"<p class='warn'>枚数チェック: NG ({total}枚、60枚である必要があります)</p>")
    if over_limit:
        html_parts.append(
            "<p class='warn'>同名カード4枚超: " + ", ".join(f"{n}({c}枚)" for n, c in over_limit.items()) + "</p>"
        )
    else:
        html_parts.append("<p class='ok'>同名カード枚数チェック: OK (5枚以上の重複なし)</p>")
    if unknown_ids:
        html_parts.append(f"<p class='warn'>カードデータに存在しないID: {', '.join(unknown_ids)}</p>")

    for stage in STAGE_ORDER:
        items = groups.get(stage)
        if not items:
            continue
        items.sort(key=lambda t: (-t[1], t[2]["カード名"]))
        stage_total = sum(c for _, c, _ in items)
        html_parts.append(f"<h2>{stage}（{stage_total}枚 / {len(items)}種）</h2><div class='grid'>")
        for cid, count, row in items:
            img_tag = f"<img src='{to_data_uri(images[cid])}'>" if cid in images else "(画像なし)"
            html_parts.append(
                "<div class='card'>"
                f"{img_tag}"
                f"<div class='count'>×{count}</div>"
                f"<div class='name'>{row['カード名']}<br>(ID:{cid})</div>"
                "</div>"
            )
        html_parts.append("</div>")

    html_parts.append("</body></html>")
    html_path = out_dir / "deck.html"
    html_path.write_text("\n".join(html_parts), encoding="utf-8")

    # ---- 一覧確認用の合成PNG ----
    poster_path = out_dir / "deck_grid.png"
    build_poster(groups, images, card_data, poster_path)

    print(f"HTMLレポート: {html_path}")
    print(f"一覧PNG: {poster_path}")
    if total != 60:
        print(f"警告: デッキ枚数が60枚ではありません ({total}枚)")
    if over_limit:
        print(f"警告: 同名カード4枚超: {over_limit}")
    if unknown_ids:
        print(f"警告: 未知のカードID: {unknown_ids}")


def build_poster(groups, images, card_data, out_path):
    cell_w, cell_h = 160, 250
    cols = 8
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 16)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 13)
    except OSError:
        font = ImageFont.load_default()
        font_small = font

    # 1パス目: 各要素の描画位置(x, y)を確定し、必要な高さを求める
    placements = []  # ("header", text, y) or ("card", payload, x, y)
    x, y = 0, 10
    for stage in STAGE_ORDER:
        items = groups.get(stage)
        if not items:
            continue
        items = sorted(items, key=lambda t: (-t[1], t[2]["カード名"]))
        if x != 0:
            y += cell_h
            x = 0
        placements.append(("header", stage, y))
        y += 30
        for item in items:
            placements.append(("card", item, x, y))
            x += 1
            if x == cols:
                x = 0
                y += cell_h
    if x != 0:
        y += cell_h

    poster = Image.new("RGB", (cell_w * cols, y + 20), "#1b1b1b")
    draw = ImageDraw.Draw(poster)
    for placement in placements:
        if placement[0] == "header":
            _, text, py = placement
            draw.text((10, py), text, fill="#ffd54f", font=font)
        else:
            _, (cid, count, row), px, py = placement
            img = images.get(cid)
            if img is not None:
                thumb = img.copy()
                thumb.thumbnail((cell_w - 10, cell_h - 50))
                poster.paste(thumb, (px * cell_w + 5, py + 5))
            draw.text(
                (px * cell_w + 5, py + cell_h - 40),
                f"x{count} {row['カード名'][:10]}",
                fill="#eeeeee",
                font=font_small,
            )

    poster.save(out_path)


if __name__ == "__main__":
    main()
