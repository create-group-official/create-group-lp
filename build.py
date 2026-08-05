"""
CREATE GROUP LP ビルドスクリプト

content/*.json（ましろが編集する領域）とHTMLテンプレート（<!-- CMS:xxx:start/end -->
マーカーで囲まれた領域）を合成し、dist/に公開用の完成HTMLを生成する。
JSON-LD（NightClub/JobPosting/FAQPage）もcontent/から再生成するため、
本文とSEO構造化データが二重管理でズレることはない。

生成物（dist/）はコミットしない前提。GitHub Actionsが毎回このスクリプトを実行し、
出力をそのままGitHub Pagesへデプロイする。

使い方：
  python build.py
"""
import json
import re
import shutil
from datetime import date
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

LP_DIR = Path(__file__).resolve().parent
CONTENT_DIR = LP_DIR / "content"
UPLOADS_DIR = LP_DIR / "uploads"
DIST_DIR = LP_DIR / "dist"

MAX_IMAGE_WIDTH = 1600
MAX_IMAGE_BYTES = 500_000

SHOP_ADDRESS = {
    "create": {"street": "栄4-10-2 第6オーシャンビル4F", "closes": "25:00"},
    "plus": {"street": "栄4-11-1 アイランドビル1F", "closes": "24:30"},
}
JOBPOSTING_IDENTIFIER = {"create": "create-host", "plus": "create-plus-host"}
JOBPOSTING_DESC = {
    "create": "在籍のほとんどが未経験からのスタート。育成プログラムであり、経験より先に「何を、どうすればいいか」を一つずつ教えてくれる。給与は日払い対応、ノルマ・罰金なし。地方出張面接対応。",
    "plus": "9割以上が未経験スタート。専属コーディネーター＋個人コンサル＋特別育成プログラムあり。給与は日払い対応、ノルマ・罰金なし。入店祝い金・寮費無料（1ヶ月）等の待遇あり。",
}


def load_json(name):
    return json.loads((CONTENT_DIR / f"{name}.json").read_text(encoding="utf-8"))


def esc(s):
    """ましろの入力はテキストとしてのみ表示する（タグ埋め込み不可にしてXSS・レイアウト崩壊を防ぐ）"""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ============================================================
# 各CMSマーカーのレンダラー
# ============================================================

def render_links_header_consult(links):
    return f'<a href="{esc(links["line_consult"])}" target="_blank" rel="noopener">お客様相談窓口</a>'


def render_links_footer_sns(links):
    return (
        '<nav class="sns">\n'
        f'    <a href="{esc(links["instagram"])}" target="_blank" rel="noopener">Instagram</a>\n'
        f'    <a href="{esc(links["line_consult"])}" target="_blank" rel="noopener">LINE</a>\n'
        '  </nav>'
    )


def render_links_recruit_cta(links):
    return (
        '<div class="cta-row reveal">\n'
        f'      <a class="btn" href="{esc(links["line_entry"])}" target="_blank" rel="noopener">Entry ／ 応募する</a>\n'
        '    </div>'
    )


def render_news(news):
    if not news:
        return (
            '<div class="inner chapter reveal">\n'
            '    <p class="chapter-en">Coming <em>Soon.</em></p>\n'
            '    <h2 class="sec-title">最新情報は近日公開</h2>\n'
            '  </div>'
        )
    items = []
    for n in news:
        title = esc(n.get("title", ""))
        heading = f'<a href="{esc(n["link"])}" target="_blank" rel="noopener">{title}</a>' if n.get("link") else title
        items.append(
            '<article class="news-item">\n'
            f'        <time>{esc(n.get("date", ""))}</time>\n'
            f'        <h3>{heading}</h3>\n'
            f'        <p>{esc(n.get("body", ""))}</p>\n'
            '      </article>'
        )
    return (
        '<div class="inner chapter reveal">\n'
        '    <div class="news-list">\n      ' + "\n      ".join(items) + '\n    </div>\n'
        '  </div>'
    )


def render_closeup(items):
    cards = [
        '<figure class="cu-card">\n'
        f'        <img src="{esc(it["image"])}" alt="{esc(it["alt"])}" loading="lazy">\n'
        '        <div class="cu-grad"></div>\n'
        '      </figure>'
        for it in items
    ]
    return "\n      ".join(cards)


def render_gallery(items):
    figs = [
        f'<figure class="grid-photo"><img src="{esc(it["image"])}" alt="{esc(it["alt"])}" loading="lazy"></figure>'
        for it in items
    ]
    return "\n    ".join(figs)


def render_shops_teaser(shops):
    cards = []
    for s in shops:
        plus_cls = " emblem-logo--plus" if s["id"] == "plus" else ""
        cards.append(
            f'<a class="store-card store-card--rich" href="{esc(s["official_url"])}" target="_blank" rel="noopener">\n'
            f'        <div class="store-photo store-photo--{esc(s["id"])}">\n'
            f'          <img src="{esc(s["photo"])}" alt="{esc(s["name"])} 店舗イメージ" loading="lazy">\n'
            '          <div class="store-photo-grad"></div>\n'
            '        </div>\n'
            f'        <img class="emblem-logo small{plus_cls}" src="{esc(s["logo"])}" alt="{esc(s["logo_alt"])}">\n'
            f'        <h3>{esc(s["name"])}</h3>\n'
            f'        <p class="store-tag">{esc(s["tag"])}</p>\n'
            f'        <p class="store-catch">{esc(s["catch"])}</p>\n'
            f'        <p class="store-copy">{esc(s["copy"])}</p>\n'
            '        <dl class="store-info">\n'
            f'          <div><dt>Open</dt><dd>{esc(s["hours"])}</dd></div>\n'
            f'          <div><dt>Tel</dt><dd>{esc(s["tel"])}</dd></div>\n'
            f'          <div><dt>Address</dt><dd>{esc(s["address"])}</dd></div>\n'
            '        </dl>\n'
            '      </a>'
        )
    return "\n      ".join(cards)


def render_shops_full(shops):
    cards = []
    for s in shops:
        plus_cls = " emblem-logo--plus" if s["id"] == "plus" else ""
        cards.append(
            '<div class="store-card store-card--rich">\n'
            f'        <div class="store-photo store-photo--{esc(s["id"])}">\n'
            f'          <img src="{esc(s["photo"])}" alt="{esc(s["name"])} 店舗イメージ" loading="lazy">\n'
            '          <div class="store-photo-grad"></div>\n'
            '        </div>\n'
            f'        <img class="emblem-logo small{plus_cls}" src="{esc(s["logo"])}" alt="{esc(s["logo_alt"])}">\n'
            f'        <h3>{esc(s["name"])}</h3>\n'
            f'        <p class="store-tag">{esc(s["tag"])}</p>\n'
            f'        <p class="store-catch">{esc(s["catch"])}</p>\n'
            f'        <p class="store-copy">{esc(s["copy"])}</p>\n'
            '        <dl class="store-info">\n'
            f'          <div><dt>Open</dt><dd>{esc(s["hours"])}</dd></div>\n'
            f'          <div><dt>Tel</dt><dd><a href="tel:{esc(s["tel_href"])}">{esc(s["tel"])}</a></dd></div>\n'
            f'          <div><dt>Address</dt><dd>{esc(s["address"])}</dd></div>\n'
            '        </dl>\n'
            f'        <a class="btn btn--sm" href="{esc(s["official_url"])}" target="_blank" rel="noopener">Official Site</a>\n'
            '      </div>'
        )
    return "\n      ".join(cards)


def render_recruit_plans(recruit):
    cards = []
    for p in recruit["plans"]:
        benefits_html = (
            f'\n          <dt>待遇</dt>\n          <dd>{esc(p["benefits"])}</dd>'
            if p.get("benefits") else ""
        )
        cards.append(
            '<div class="recruit-plan reveal">\n'
            '        <figure class="recruit-plan-photo">\n'
            f'          <img src="{esc(p["photo"])}" alt="{esc(p["name"])}" loading="lazy">\n'
            '        </figure>\n'
            f'        <h3>{esc(p["name"])}</h3>\n'
            f'        <p class="plan-tag">{esc(p["tag"])}</p>\n'
            '        <dl>\n'
            '          <dt>給与</dt>\n'
            f'          <dd>{esc(p["salary"])}</dd>{benefits_html}\n'
            '          <dt>勤務</dt>\n'
            f'          <dd>{esc(p["hours"])}</dd>\n'
            '          <dt>応募資格</dt>\n'
            f'          <dd>{esc(p["qualification"])}</dd>\n'
            '          <dt>育成</dt>\n'
            f'          <dd>{esc(p["training"])}</dd>\n'
            '        </dl>\n'
            '      </div>'
        )
    return "\n      ".join(cards)


def render_recruit_faq(recruit):
    items = [
        '<div class="faq-item">\n'
        f'        <p class="faq-q"><span class="qa-mark">Q.</span><span>{esc(f["q"])}</span></p>\n'
        f'        <p class="faq-a"><span class="qa-mark">A.</span><span>{esc(f["a"])}</span></p>\n'
        '      </div>'
        for f in recruit["faq"]
    ]
    return "\n      ".join(items)


def render_jsonld_nightclubs(shops):
    blocks = []
    for s in shops:
        addr = SHOP_ADDRESS[s["id"]]
        data = {
            "@context": "https://schema.org",
            "@type": "NightClub",
            "name": s["name"],
            "url": "https://mahiro-jpn.github.io/create-group-lp/shoplist.html",
            "sameAs": ["https://www.instagram.com/create_group_/"],
            "telephone": s["tel"],
            "address": {
                "@type": "PostalAddress",
                "streetAddress": addr["street"],
                "addressLocality": "名古屋市中区",
                "addressRegion": "愛知県",
                "addressCountry": "JP",
            },
            "openingHoursSpecification": [{
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                "opens": "20:00",
                "closes": addr["closes"],
            }],
            "parentOrganization": {"@type": "Organization", "name": "CREATE GROUP"},
        }
        blocks.append('<script type="application/ld+json">\n' + json.dumps(data, ensure_ascii=False, indent=2) + '\n</script>')
    return "\n".join(blocks)


def render_jsonld_recruit(recruit):
    faq_data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
            for f in recruit["faq"]
        ],
    }
    blocks = ['<script type="application/ld+json">\n' + json.dumps(faq_data, ensure_ascii=False, indent=2) + '\n</script>']
    for p in recruit["plans"]:
        addr = SHOP_ADDRESS[p["shop_id"]]
        job_data = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "ホスト（未経験歓迎）",
            "description": JOBPOSTING_DESC.get(p["shop_id"], p.get("training", "")),
            "identifier": {"@type": "PropertyValue", "name": "CREATE GROUP", "value": JOBPOSTING_IDENTIFIER.get(p["shop_id"], p["shop_id"])},
            "datePosted": recruit["job_posted_date"],
            "validThrough": recruit["job_valid_through"],
            "employmentType": "OTHER",
            "hiringOrganization": {
                "@type": "Organization",
                "name": p["name"],
                "sameAs": "https://mahiro-jpn.github.io/create-group-lp/shoplist.html",
            },
            "jobLocation": {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": addr["street"],
                    "addressLocality": "名古屋市中区",
                    "addressRegion": "愛知県",
                    "addressCountry": "JP",
                },
            },
            "baseSalary": {
                "@type": "MonetaryAmount",
                "currency": "JPY",
                "value": {"@type": "QuantitativeValue", "value": p["salary_value"], "minValue": p["salary_min"], "unitText": "DAY"},
            },
        }
        blocks.append('<script type="application/ld+json">\n' + json.dumps(job_data, ensure_ascii=False, indent=2) + '\n</script>')
    return "\n".join(blocks)


def build_marker_renderers():
    links = load_json("links")
    shops = load_json("shops")
    recruit = load_json("recruit")
    news = load_json("news")
    closeup = load_json("closeup")
    gallery = load_json("gallery")
    return {
        "links:header-consult": render_links_header_consult(links),
        "links:footer-sns": render_links_footer_sns(links),
        "links:recruit-cta": render_links_recruit_cta(links),
        "news": render_news(news),
        "closeup": render_closeup(closeup),
        "gallery": render_gallery(gallery),
        "shops-teaser": render_shops_teaser(shops),
        "shops-full": render_shops_full(shops),
        "recruit-plans": render_recruit_plans(recruit),
        "recruit-faq": render_recruit_faq(recruit),
        "jsonld-nightclubs": render_jsonld_nightclubs(shops),
        "jsonld-recruit": render_jsonld_recruit(recruit),
    }


MARKER_RE = re.compile(r"(<!-- CMS:([a-zA-Z0-9:_-]+):start -->)(.*?)(<!-- CMS:\2:end -->)", re.DOTALL)


def apply_markers(html, renderers, filename):
    missing = []

    def repl(m):
        name = m.group(2)
        if name not in renderers:
            missing.append(name)
            return m.group(0)
        return f"{m.group(1)}\n{renderers[name]}\n{m.group(4)}"

    result = MARKER_RE.sub(repl, html)
    if missing:
        raise KeyError(f"{filename}: 未知のCMSマーカー {missing}")
    return result


def compress_image(src, dest):
    if Image is None or src.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        shutil.copy2(src, dest)
        return
    img = Image.open(src)
    if img.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / img.width
        img = img.resize((MAX_IMAGE_WIDTH, int(img.height * ratio)), Image.LANCZOS)
    if src.suffix.lower() in (".jpg", ".jpeg"):
        img = img.convert("RGB")
        quality = 85
        while True:
            img.save(dest, format="JPEG", quality=quality, optimize=True)
            if dest.stat().st_size <= MAX_IMAGE_BYTES or quality <= 40:
                break
            quality -= 10
    else:
        img.save(dest, optimize=True)


def update_sitemap(xml_text):
    today = date.today().isoformat()
    return re.sub(r"<lastmod>.*?</lastmod>", f"<lastmod>{today}</lastmod>", xml_text)


def main():
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir()

    renderers = build_marker_renderers()

    for html_file in LP_DIR.glob("*.html"):
        html = html_file.read_text(encoding="utf-8")
        html = apply_markers(html, renderers, html_file.name)
        (DIST_DIR / html_file.name).write_text(html, encoding="utf-8")

    if (LP_DIR / "robots.txt").exists():
        shutil.copy2(LP_DIR / "robots.txt", DIST_DIR / "robots.txt")

    sitemap_src = LP_DIR / "sitemap.xml"
    if sitemap_src.exists():
        (DIST_DIR / "sitemap.xml").write_text(update_sitemap(sitemap_src.read_text(encoding="utf-8")), encoding="utf-8")

    shutil.copytree(LP_DIR / "assets", DIST_DIR / "assets")

    admin_src = LP_DIR / "admin"
    if admin_src.exists():
        shutil.copytree(admin_src, DIST_DIR / "admin")

    material_src = LP_DIR / "LP_素材"
    if material_src.exists():
        shutil.copytree(material_src, DIST_DIR / "LP_素材", symlinks=False)

    if UPLOADS_DIR.exists():
        dist_uploads = DIST_DIR / "uploads"
        dist_uploads.mkdir(exist_ok=True)
        for f in UPLOADS_DIR.rglob("*"):
            if f.is_file():
                rel = f.relative_to(UPLOADS_DIR)
                dest = dist_uploads / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                compress_image(f, dest)

    print(f"[DONE] dist/ に生成完了: {DIST_DIR}")


if __name__ == "__main__":
    main()
