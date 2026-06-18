"""Card_ID List_JP.pdf から全カードの券面画像を抜き出し、deck-maker/images/{id}.png として保存する。

使い方:
    source env/venv311/bin/activate
    python explore/extract_card_images.py
"""
from pathlib import Path

import fitz
from PIL import Image
import io

ROOT = Path(__file__).resolve().parent.parent
CARD_PDF = ROOT / "pokemon-tcg-ai-battle" / "Card_ID List_JP.pdf"
OUT_DIR = ROOT / "deck-maker" / "images"


def build_id_to_page_map(doc):
    import re

    mapping = {}
    for i in range(len(doc)):
        text = doc[i].get_text()
        ids = re.findall(r"(?m)^(\d+)$", text)
        links = sorted(doc[i].get_links(), key=lambda l: l["from"].y0)
        if not ids or len(ids) != len(links):
            break
        for cid, link in zip(ids, links):
            mapping[cid] = link["page"]
    return mapping


def render_card_image(doc, page_index, dpi=150):
    page = doc[page_index]
    infos = page.get_image_info()
    pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(*infos[0]["bbox"]) if infos else None)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(CARD_PDF))
    id_to_page = build_id_to_page_map(doc)
    print(f"id_to_page entries: {len(id_to_page)}")

    saved, missing = 0, []
    for cid, page_index in id_to_page.items():
        out_path = OUT_DIR / f"{cid}.png"
        try:
            img = render_card_image(doc, page_index)
            img.thumbnail((300, 420))
            img.save(out_path, format="PNG", optimize=True)
            saved += 1
        except Exception as e:
            missing.append((cid, str(e)))

    print(f"saved: {saved}")
    if missing:
        print(f"missing/failed: {len(missing)}")
        for cid, err in missing[:20]:
            print(f"  {cid}: {err}")


if __name__ == "__main__":
    main()
