# /// script
# requires-python = ">=3.10"
# dependencies = ["lxml>=5,<7"]
# ///
"""Colt Studio scene, DVD group, and performer scraper for Stash."""

import json
import re
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from lxml import etree, html
except ModuleNotFoundError:
    print(
        "[Error] Colt Studio scrape failed: the Python module lxml is not installed "
        "for the Python that runs Stash. Install lxml>=5,<7 there.",
        file=sys.stderr,
    )
    print("null")
    sys.exit(1)

SITE = "https://www.coltstudiogroup.com"
STORE = "https://coltstudiostore.com"
PAGE_HOSTS = {
    "www.coltstudiogroup.com",
    "coltstudiogroup.com",
    "www.coltstudiostore.com",
    "coltstudiostore.com",
}
STUDIOS = {
    "colt": "Colt Studio Group",
    "colt studio": "Colt Studio Group",
    "colt studio group": "Colt Studio Group",
    "buckshot": "Buckshot",
    "buckshot productions": "Buckshot",
    "olympus": "Olympus",
    "olympus studio": "Olympus",
    "minute man": "Minute Man",
}
DETAILS = (
    '//div[contains(concat(" ", normalize-space(@class), " "), " container_styled_1 ")]'
)
SIDEBAR = '//div[contains(concat(" ", normalize-space(@class), " "), " modelProfileSidebar ")]'


def clean(value):
    return " ".join(str(value).split())


def text(node):
    return clean(node.text_content())


def first(node, xpath):
    values = node.xpath(xpath)
    if not values:
        return ""
    return text(values[0]) if hasattr(values[0], "text_content") else clean(values[0])


def unique(values):
    return list(dict.fromkeys(value for value in values if value))


def tags(values):
    return [{"name": value} for value in unique(clean(v) for v in values)]


def page_url(url, kind=None):
    """Validate page URLs before requests, including redirects and canonical links."""
    p = urlsplit(url)
    if (
        p.scheme not in {"http", "https"}
        or p.hostname not in PAGE_HOSTS
        or p.username
        or p.password
        or p.port not in {None, 80, 443}
    ):
        raise ValueError("Expected a Colt Studio or Colt Studio Store URL")
    host = SITE if "coltstudiogroup" in p.hostname else STORE
    path = p.path.rstrip("/")
    if kind in {"scene", "performer"}:
        prefix = "scene" if kind == "scene" else "profile"
        if host != SITE or not re.fullmatch(rf"/{prefix}/\d+(?:-[^/]+)?", path):
            raise ValueError(f"Expected a Colt {prefix} URL")
    if kind == "group":
        match = re.fullmatch(r"/products/[^/]+", path)
        if host != STORE or not match:
            raise ValueError("Expected a Colt Store DVD product URL")
    return host + path


class ColtRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        page_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url):
    url = page_url(url)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    with build_opener(ColtRedirects()).open(request, timeout=30) as response:
        data = response.read(8_000_001)
    if len(data) > 8_000_000:
        raise ValueError("Colt page exceeds the 8 MB size limit")
    return html.fromstring(data, base_url=url)


def canonical(doc, url, kind):
    candidate = first(doc, '//link[@rel="canonical"]/@href')
    result = (
        page_url(urljoin(url, candidate), kind) if candidate else page_url(url, kind)
    )
    original = page_url(url, kind)
    # A redirect to a different entity must not silently scrape the wrong item.
    if kind == "group":
        same = result == original
    else:
        same = (
            result.split("/")[-1].split("-")[0] == original.split("/")[-1].split("-")[0]
        )
    if not same:
        raise ValueError("Colt page canonical URL points to a different item")
    return result


def explicit_date(value):
    """Accept full dates only. Never turn a year into an invented January 1 date."""
    value = clean(value)
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def labeled_value(doc, label):
    """Read explicit labels, not words in marketing prose or scene titles."""
    for node in doc.xpath(".//li | .//p | .//h5 | .//tr"):
        for line in paragraphs([node]).splitlines():
            match = re.match(rf"^\s*(?:{label})\s*:\s*(.+)$", line, re.IGNORECASE)
            if match:
                return match[1]
    return ""


def studio_name(*values):
    for value in values:
        name = STUDIOS.get(clean(value).casefold())
        if name and name != "Colt Studio Group":
            return name
    return "Colt Studio Group"


def studio(name):
    result = {"name": name}
    if name == "Colt Studio Group":
        result["urls"] = [SITE]
    return result


def paragraphs(nodes):
    """Preserve paragraph and line boundaries without including scripts or images."""
    output = []
    for node in nodes:
        copy = html.fromstring(html.tostring(node))
        for unwanted in copy.xpath(".//script | .//style"):
            unwanted.drop_tree()
        for br in copy.xpath(".//br"):
            br.tail = "\n" + (br.tail or "")
        for block in copy.xpath(".//p | .//div | .//li | .//tr | .//h5"):
            block.text = "\n" + (block.text or "")
            block.tail = "\n" + (block.tail or "")
        output.extend(
            clean(line) for line in copy.text_content().splitlines() if clean(line)
        )
    return "\n\n".join(unique(output))


def parse_scene(doc, url):
    url = canonical(doc, url, "scene")
    code = re.search(r"/scene/(\d+)", url)[1]
    title = first(doc, '//h2[contains(@class,"sectionMainTitle")]')
    if not title:
        raise ValueError("Scene title missing. Colt returned an unexpected page")
    result = {"title": title, "code": code, "urls": [url]}
    result["studio"] = studio(studio_name(labeled_value(doc, "Studio|Label|Brand")))
    result["details"] = paragraphs(
        doc.xpath(DETAILS + '//div[contains(@class,"p-5")]/p')
    )
    result["tags"] = tags(
        text(n) for n in doc.xpath(DETAILS + '//h5[contains(.,"Categories")]/a')
    )
    performers = []
    for anchor in doc.xpath(DETAILS + '//span[contains(@class,"perfImage")]/a'):
        name = text(anchor)
        href = anchor.get("href", "")
        if name and href:
            performer = {
                "name": name,
                "urls": [page_url(urljoin(url, href), "performer")],
            }
            if performer not in performers:
                performers.append(performer)
    result["performers"] = performers
    # Never search the related-scenes section. Require this scene's ID in the filename.
    own_photo = f"/scn_{code}_"
    images = doc.xpath(
        '//div[@id="playerWrap"]//img/@src | //div[@id="playerWrap"]//video/@poster'
    )
    image = next((u for u in images if own_photo in u), "")
    if not image:
        image = first(doc, '//meta[@property="og:image"]/@content')
        if own_photo not in image:
            image = ""
    if image:
        result["image"] = urljoin(url, image)
    date = explicit_date(labeled_value(doc, "Release Date|Released|Date"))
    if not date:
        details = first(
            doc, DETAILS + '//h5[starts-with(normalize-space(.),"Details:")]'
        )
        match = re.match(r"Details:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", details)
        date = explicit_date(match[1]) if match else ""
    if date:
        result["date"] = date
    director = labeled_value(doc, "Director|Directed by")
    if director:
        result["director"] = director
    return result


def dvd_links(doc, url):
    links = []
    for href in doc.xpath(DETAILS + "//a[@href]/@href"):
        try:
            link = page_url(urljoin(url, href), "group")
        except ValueError:
            continue
        links.append(link)
    return unique(links)


def product_data(doc):
    """Use embedded Shopify data, avoiding a second request to the product API."""
    decoder = json.JSONDecoder()
    for script in doc.xpath("//script[not(@src)]/text()"):
        for match in re.finditer(
            r"(?:window\.pushupProduct|boosterParams\.product|_BISConfig\.product)\s*=\s*",
            script,
        ):
            try:
                product, _ = decoder.raw_decode(script[match.end() :])
            except (ValueError, TypeError):
                continue
            if (
                isinstance(product, dict)
                and product.get("title")
                and product.get("handle")
            ):
                return product
    raise ValueError("DVD product data missing. Colt Store returned an unexpected page")


def artwork_url(value, base):
    """Shopify product images are originals, unlike resized social sharing images."""
    if isinstance(value, dict):
        value = value.get("src", "")
    return urljoin(base, value) if value else ""


def parse_group(doc, url):
    url = canonical(doc, url, "group")
    product = product_data(doc)
    if product.get("handle") != url.rsplit("/", 1)[-1]:
        raise ValueError("Embedded DVD product does not match the requested URL")
    if not re.search(r"\bdvd\b", product.get("type", ""), re.IGNORECASE):
        raise ValueError("The Colt Store product is not a DVD")
    description = html.fromstring(
        "<div>" + (product.get("description") or "") + "</div>"
    )
    # Remove scene promotion rows, but preserve the DVD's own table-cell text.
    for row in description.xpath(
        ".//tr[.//a[contains(@href,'/scene/')] and not(.//tr)]"
    ):
        row.drop_tree()
    raw_tags = product.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(",")
    name = studio_name(
        labeled_value(description, "Studio|Label|Brand"),
        product.get("vendor", ""),
        *raw_tags,
    )
    result = {"name": clean(product["title"]), "urls": [url], "studio": studio(name)}
    synopsis = paragraphs([description])
    skus = unique(clean(v.get("sku", "")) for v in product.get("variants", []))
    if skus:
        synopsis += "\n\nDVD SKU: " + ", ".join(skus)
    if synopsis:
        result["synopsis"] = synopsis.strip()
    director = re.search(
        r"(?:Directed by|Director\s*:)\s*([^\n]+)", synopsis, re.IGNORECASE
    )
    if director:
        result["director"] = director[1].strip(" -")
    runtime = re.search(
        r"(?:TRT(?:\s+of)?|Run(?:ning)?\s*Time|Duration)\s*:?\s*(\d+)\s*(?:mins?|minutes?)\b",
        synopsis,
        re.IGNORECASE,
    )
    if runtime:
        result["duration"] = str(int(runtime[1]) * 60)
    date = explicit_date(labeled_value(description, "Release Date|Released|Date"))
    if date:
        result["date"] = date
    # Exclude merchandising, inventory, and brand labels from product tags.
    content_tags = []
    for value in raw_tags:
        value = clean(value)
        if (
            value.casefold() not in STUDIOS
            and value.casefold() not in {"all", "dvd", "dvds"}
            and not re.search(
                r"%|\$|\b(?:sale|off|discount|clearance|shipping|stock|sold|inventory|featured|new arrivals|best sellers?)\b",
                value,
                re.IGNORECASE,
            )
        ):
            content_tags.append(value)
    for node in description.xpath(
        './/*[self::p or self::li][starts-with(normalize-space(.),"Categories:") or starts-with(normalize-space(.),"Tags:")]'
    ):
        value = text(node).split(":", 1)[1]
        content_tags.extend(clean(v) for v in value.split(","))
    if content_tags:
        result["tags"] = tags(content_tags)
    images = unique(artwork_url(v, url) for v in product.get("images", []))
    for key, marker in (
        ("front_image", r"(?:^|[_\- ])(?:f|front)(?:[_\-. ]|$)"),
        ("back_image", r"(?:^|[_\- ])(?:b|back)(?:[_\-. ]|$)"),
    ):
        match = next(
            (
                image
                for image in images
                if re.search(
                    marker, urlsplit(image).path.rsplit("/", 1)[-1], re.IGNORECASE
                )
            ),
            "",
        )
        if match:
            result[key] = match
    # Do not assume the second product image is a back cover (often a montage).
    if "front_image" not in result:
        fallback = next(
            (image for image in images if image != result.get("back_image")), ""
        )
        if fallback:
            result["front_image"] = fallback
    return result


def parse_performer(doc, url):
    url = canonical(doc, url, "performer")
    name = first(doc, SIDEBAR + '//div[@class="main_title"]/h3')
    if not name:
        raise ValueError("Performer name missing. Colt returned an unexpected page")
    result = {"name": name, "gender": "MALE", "urls": [url]}
    result["tags"] = tags(
        text(n)
        for n in doc.xpath(
            SIDEBAR
            + '//a[contains(@href,"/models/tag/") or contains(@class,"tagsRnd")]'
        )
    )
    details = paragraphs(
        doc.xpath(SIDEBAR + '//div[@class="main_title"]/p[not(@class)]')
    )
    if details:
        result["details"] = details
    images = doc.xpath(
        SIDEBAR + '//div[@class="profile"]//img[contains(@class,"img-responsive")]/@src'
    )
    if images:
        result["images"] = unique(urljoin(url, image) for image in images)
    for href in doc.xpath(SIDEBAR + "//a[@href]/@href"):
        absolute = urljoin(url, href)
        if urlsplit(absolute).hostname in {
            "twitter.com",
            "www.twitter.com",
            "x.com",
            "www.x.com",
            "instagram.com",
            "www.instagram.com",
        }:
            result["urls"].append(absolute)
    for item in doc.xpath(SIDEBAR + "//li[strong]"):
        label = clean(item.text or "").casefold()
        value = first(item, "./strong")
        if label == "height":
            match = re.fullmatch(r"(\d+)\s*[′'’]\s*(\d+)\s*[″\"”]?", value)
            if match:
                result["height"] = str(
                    round((int(match[1]) * 12 + int(match[2])) * 2.54)
                )
        elif label == "weight":
            match = re.fullmatch(r"([\d.]+)\s*(?:pounds|lbs?)", value, re.IGNORECASE)
            if match:
                result["weight"] = str(round(float(match[1]) * 0.45359237))
        elif label == "dick size":
            match = re.fullmatch(r"([\d.]+)\s*inches", value, re.IGNORECASE)
            if match:
                result["penis_length"] = str(round(float(match[1]) * 2.54, 2))
        elif "cut" in label:
            cut = {"cut": "CUT", "uncut": "UNCUT"}.get(value.casefold())
            if cut:
                result["circumcised"] = cut
        elif label == "position":
            result["tags"] = tags([t["name"] for t in result["tags"]] + [value])
    return result


def scrape(kind, url, fetch=fetch_page):
    url = page_url(url, kind)
    doc = fetch(url)
    if kind == "group":
        return parse_group(doc, url)
    if kind == "performer":
        return parse_performer(doc, url)
    result = parse_scene(doc, url)
    explicit_studio = (
        clean(labeled_value(doc, "Studio|Label|Brand")).casefold() in STUDIOS
    )
    groups = []
    for link in dvd_links(doc, url):
        try:
            group = parse_group(fetch(link), link)
        except (HTTPError, URLError, ValueError, OSError, etree.LxmlError) as error:
            print(f"[Warning] DVD lookup failed for {link}: {error}", file=sys.stderr)
            continue
        groups.append(group)
        if not explicit_studio and result["studio"]["name"] == "Colt Studio Group":
            result["studio"] = group["studio"]
    if groups:
        result["groups"] = groups
    return result


def main():
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"scene", "group", "performer"}:
            raise ValueError(
                "Expected scene, group, or performer mode and JSON input on stdin"
            )
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or not isinstance(payload.get("url"), str):
            raise TypeError('Expected JSON input with a string "url" field')
        result = scrape(sys.argv[1], payload["url"])
    except (
        ValueError,
        TypeError,
        HTTPError,
        URLError,
        OSError,
        etree.LxmlError,
    ) as error:
        print(f"[Error] Colt Studio scrape failed: {error}", file=sys.stderr)
        print("null")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
