"""Offline regression tests. Fixtures model the public Colt page structure."""

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
import yaml
from lxml import html

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coltstudio", ROOT / "coltstudio.py")
colt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(colt)

SCENE_URL = colt.SITE + "/scene/395-red-hot-scene-1"
GROUP_URL = colt.STORE + "/products/red-hot"
PROFILE_URL = colt.SITE + "/profile/334-seth-fornea"
HOT_COP_URL = colt.SITE + "/profile/423-hot-cop"
PHOTO = "https://static.coltstudiogroup.com/_thumbs/a/scn_395_full.jpg"
THUMB = "https://static.coltstudiogroup.com/_thumbs/b/scn_395_small.jpg"


def scene_page(photo=True, dvd=True, extras="", performers=True):
    doc = html.fromstring(f"""<html><head>
      <link rel="canonical" href="{SCENE_URL}">
      <meta property="og:image" content="{THUMB}"></head><body>
      <h2 class="main_title sectionMainTitle">RED HOT Scene 1</h2>
      <div id="playerWrap">{f'<img src="{PHOTO}">' if photo else ""}
        <img src="/playBtn.png"></div>
      <div class="row container_styled_1">
        {'<a href="http://coltstudiostore.com/products/red-hot">Buy on DVD</a>' if dvd else ""}
        <div class="p-5"><p>A <em>complete</em> description.</p><p>Second paragraph.</p>
          <h5>Categories: <a href="/scenes/category/1">Muscle</a>, <a href="/scenes/category/2">Solo</a></h5>
          <h5>Details: <i></i>11 min</h5>
          <span class="perfImage"><a href="/profile/423-hot-cop"><img src="/p.jpg">Hot Cop</a></span>
          <span class="perfImage"><a href="/profile/334-seth-fornea">Seth Fornea</a></span>
          {extras}
        </div>
      </div>
      <div class="related"><h2>Wrong title</h2><img src="/scn_999_wrong.jpg">
        <a href="/profile/999-wrong">Wrong performer</a><p>Wrong details</p></div>
      </body></html>""")
    if not performers:
        for node in doc.xpath('//span[@class="perfImage"]'):
            node.drop_tree()
    return doc


def group_page(**changes):
    product = {
        "title": "Red Hot",
        "handle": "red-hot",
        "type": "DVD",
        "vendor": "COLT Studio",
        "description": """<table><tr><td><p>DVD synopsis.</p>
        <p>Directed by Jane Director<br>TRT of 41 mins on one disc</p></td></tr>
        <tr><td><a href="https://www.coltstudiogroup.com/scene/395-red-hot-scene-1">Watch scene</a>
        <p>Scene advertising, not the synopsis.</p></td></tr></table>""",
        "tags": [
            "COLT",
            "DVD",
            "All",
            "50% OFF DVDs Now!",
            "Featured",
            "Muscle",
            "Vintage",
        ],
        "images": [
            "//coltstudiostore.com/cdn/shop/products/MAN001_F_uuid.jpg?v=1",
            "//coltstudiostore.com/cdn/shop/products/MAN001_Store.jpg?v=1",
        ],
        "variants": [{"sku": "MAN-001D"}],
        "published_at": "2026-10-30T12:00:00Z",
        "created_at": "2020-01-01T00:00:00Z",
    }
    product.update(changes)
    return html.fromstring(f"""<html><head><link rel="canonical" href="{GROUP_URL}"></head>
      <body><script>window.pushupProduct = {json.dumps(product)};
      window.unrelated = true;</script><div>Recommended products</div></body></html>""")


class LabelTests(unittest.TestCase):
    def test_lines_preserve_node_order_and_paragraph_boundaries(self):
        doc = html.fromstring("""<div>
          <h5>Brand: Olympus</h5>
          <table><tr><td>Studio: Buckshot<br>Director: First Director
          <p>Released: 2004-05-06</p></td></tr></table>
          <ul><li>Label: Minute Man</li></ul>
          <p>Director: Second Director</p></div>""")
        lines = colt.label_lines(doc)
        self.assertEqual(
            lines,
            [
                "Brand: Olympus",
                "Studio: Buckshot",
                "",
                "Director: First Director",
                "",
                "Released: 2004-05-06",
                "Released: 2004-05-06",
                "Label: Minute Man",
                "Director: Second Director",
            ],
        )
        self.assertEqual(colt.labeled_value(lines, "Studio|Label|Brand"), "Olympus")
        self.assertEqual(
            colt.labeled_value(lines, "Director|Directed by"), "First Director"
        )
        self.assertEqual(
            colt.labeled_value(lines, "Release Date|Released|Date"), "2004-05-06"
        )

    def test_only_explicit_labels_in_supported_nodes_match(self):
        doc = html.fromstring("""<div>
          <div>Studio: Buckshot</div><h2>Director: Wrong Director</h2>
          <p>Prose about Studio: Buckshot<script>Director: Script</script>
          <style>Director: Style</style></p>
          <p>  dIrEcTeD by : <em>Jane Director</em><br>Date: 2004</p>
          <li>Studio:</li></div>""")
        lines = colt.label_lines(doc)
        self.assertEqual(colt.labeled_value(lines, "Studio|Label|Brand"), "")
        self.assertEqual(
            colt.labeled_value(lines, "Director|Directed by"), "Jane Director"
        )
        self.assertEqual(
            colt.labeled_value(lines, "Release Date|Released|Date"), "2004"
        )


class SceneTests(unittest.TestCase):
    def test_scrape_extracts_label_lines_and_studio_only_once(self):
        doc = scene_page(dvd=False, extras="<h5>Studio: Olympus</h5>", performers=False)
        with (
            patch.object(colt, "label_lines", wraps=colt.label_lines) as extract,
            patch.object(colt, "labeled_value", wraps=colt.labeled_value) as lookup,
        ):
            result = colt.scrape("scene", SCENE_URL, lambda url: doc)
        extract.assert_called_once_with(doc)
        self.assertEqual(
            [call.args[1] for call in lookup.call_args_list],
            [
                "Studio|Label|Brand",
                "Release Date|Released|Date",
                "Director|Directed by",
            ],
        )
        self.assertEqual(result, colt.parse_scene(doc, SCENE_URL))

    def test_label_lines_are_not_stale_between_parses(self):
        doc = scene_page(extras="<h5>Studio: Olympus</h5>")
        self.assertEqual(colt.parse_scene(doc, SCENE_URL)["studio"]["name"], "Olympus")
        doc.xpath('//h5[starts-with(.,"Studio:")]')[0].text = "Studio: Buckshot"
        self.assertEqual(colt.parse_scene(doc, SCENE_URL)["studio"]["name"], "Buckshot")
        self.assertEqual(
            colt.parse_scene(scene_page(), SCENE_URL)["studio"]["name"],
            "Colt Studio Group",
        )

    def test_main_image_not_social_thumbnail(self):
        result = colt.parse_scene(scene_page(), SCENE_URL)
        self.assertEqual(result["image"], PHOTO)
        self.assertEqual(result["code"], "395")
        self.assertEqual(
            result["details"], "A complete description.\n\nSecond paragraph."
        )
        self.assertEqual(result["tags"], [{"name": "Muscle"}, {"name": "Solo"}])

    def test_all_source_credits_are_preserved(self):
        self.assertEqual(
            [
                p["name"]
                for p in colt.parse_scene(scene_page(), SCENE_URL)["performers"]
            ],
            ["Hot Cop", "Seth Fornea"],
        )

    def test_social_fallback(self):
        self.assertEqual(
            colt.parse_scene(scene_page(photo=False), SCENE_URL)["image"], THUMB
        )

    def test_foreign_image_not_returned(self):
        doc = scene_page(photo=False)
        doc.xpath('//meta[@property="og:image"]')[0].set(
            "content", "/scn_999_wrong.jpg"
        )
        self.assertNotIn("image", colt.parse_scene(doc, SCENE_URL))

    def test_missing_date_is_not_runtime(self):
        self.assertNotIn("date", colt.parse_scene(scene_page(), SCENE_URL))

    def test_full_date(self):
        doc = scene_page(extras="<p>Release Date: October 30, 2006</p>")
        self.assertEqual(colt.parse_scene(doc, SCENE_URL)["date"], "2006-10-30")

    def test_details_date_format(self):
        doc = scene_page()
        doc.xpath('//h5[starts-with(.,"Details:")]')[0].text = "Details: Oct 30, 2006 "
        self.assertEqual(colt.parse_scene(doc, SCENE_URL)["date"], "2006-10-30")

    def test_explicit_scene_label(self):
        result = colt.parse_scene(
            scene_page(extras="<h5>Studio: Buckshot</h5>"), SCENE_URL
        )
        self.assertEqual(result["studio"]["name"], "Buckshot")

    def test_umbrella_fallback_without_title_guessing(self):
        doc = scene_page()
        doc.xpath("//h2")[0].text = "BUCKSHOT Scene 1"
        self.assertEqual(
            colt.parse_scene(doc, SCENE_URL)["studio"]["name"], "Colt Studio Group"
        )

    def test_direct_dvd_link_and_deduplication(self):
        doc = scene_page()
        area = doc.xpath(colt.DETAILS)[0]
        area.append(html.fromstring(f'<a href="{GROUP_URL}">Buy again</a>'))
        self.assertEqual(colt.dvd_links(doc, SCENE_URL), [GROUP_URL])

    def test_broken_dvd_does_not_lose_scene(self):
        def fetch(url):
            if url == SCENE_URL:
                return scene_page(performers=False)
            raise HTTPError(url, 429, "Too Many Requests", {}, None)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = colt.scrape("scene", SCENE_URL, fetch)
        self.assertEqual(result["title"], "RED HOT Scene 1")
        self.assertNotIn("groups", result)
        self.assertIn("429", stderr.getvalue())

    def test_scene_returns_linked_group(self):
        pages = {
            SCENE_URL: scene_page(performers=False),
            GROUP_URL: group_page(tags=["Buckshot"]),
        }
        result = colt.scrape("scene", SCENE_URL, pages.__getitem__)
        self.assertEqual(result["groups"][0]["name"], "Red Hot")
        self.assertEqual(result["studio"]["name"], "Buckshot")
        self.assertNotIn("scene_index", result["groups"][0])

    def test_null_dvd_type_does_not_lose_scene(self):
        pages = {
            SCENE_URL: scene_page(performers=False),
            GROUP_URL: group_page(type=None),
        }
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = colt.scrape("scene", SCENE_URL, pages.__getitem__)
        self.assertEqual(result, colt.parse_scene(pages[SCENE_URL], SCENE_URL))
        self.assertIn(f"[Warning] DVD lookup failed for {GROUP_URL}", stderr.getvalue())
        self.assertIn("not a DVD", stderr.getvalue())

    def test_dvd_parse_errors_do_not_stop_later_lookups(self):
        second_url = colt.STORE + "/products/second-dvd"
        doc = scene_page(performers=False)
        doc.xpath(colt.DETAILS)[0].append(
            html.fromstring(f'<a href="{second_url}">Another DVD</a>')
        )
        pages = {
            SCENE_URL: doc,
            GROUP_URL: group_page(),
            second_url: group_page(handle="second-dvd"),
        }
        pages[second_url].xpath('//link[@rel="canonical"]')[0].set("href", second_url)
        group = colt.parse_group(pages[second_url], second_url)
        for error in (TypeError("Unexpected type"), AttributeError("Unexpected shape")):
            with self.subTest(error=type(error).__name__):
                stderr = io.StringIO()
                with (
                    patch.object(colt, "parse_group", side_effect=[error, group]),
                    contextlib.redirect_stderr(stderr),
                ):
                    result = colt.scrape("scene", SCENE_URL, pages.__getitem__)
                self.assertEqual(result["title"], "RED HOT Scene 1")
                self.assertEqual(result["groups"], [group])
                self.assertIn(
                    f"[Warning] DVD lookup failed for {GROUP_URL}: {error}",
                    stderr.getvalue(),
                )

    def test_scene_without_dvd_or_performers_needs_one_request(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return scene_page(dvd=False, performers=False)

        self.assertNotIn("groups", colt.scrape("scene", SCENE_URL, fetch))
        self.assertEqual(calls, [SCENE_URL])

    def test_explicit_scene_studio_takes_precedence(self):
        for name in ("Colt Studio Group", "Olympus"):
            with self.subTest(name=name):
                pages = {
                    SCENE_URL: scene_page(
                        extras=f"<h5>Studio: {name}</h5>", performers=False
                    ),
                    GROUP_URL: group_page(tags=["Buckshot"]),
                }
                result = colt.scrape("scene", SCENE_URL, pages.__getitem__)
                self.assertEqual(result["studio"]["name"], name)

    def test_unknown_or_empty_scene_label_still_allows_dvd_fallback(self):
        for label in ("Unknown studio", ""):
            with self.subTest(label=label):
                pages = {
                    SCENE_URL: scene_page(
                        extras=f"<h5>Studio: {label}</h5>", performers=False
                    ),
                    GROUP_URL: group_page(tags=["Buckshot"]),
                }
                result = colt.scrape("scene", SCENE_URL, pages.__getitem__)
                self.assertEqual(result["studio"]["name"], "Buckshot")

    def test_wrong_canonical_is_rejected(self):
        doc = scene_page()
        doc.xpath('//link[@rel="canonical"]')[0].set(
            "href", colt.SITE + "/scene/999-other"
        )
        with self.assertRaises(ValueError):
            colt.parse_scene(doc, SCENE_URL)


class GroupTests(unittest.TestCase):
    def test_best_of_colt_synopsis_excludes_specs_and_shipping(self):
        doc = group_page(
            title="Best of Colt Films 5 & 6",
            description="""<table><tr><td>Compilation synopsis.<br><br>
            A second paragraph.<br><br>
            - Directed by Rip Colt<br>
            - TRT of 220 mins on one disc<br>
            - Region Free, Photo Galleries and Previews
            <p>**Please note this DVD ships in our White Label DVD Wallet packaging.</p>
            </td></tr>
            <tr><td><a href="https://www.coltstudiogroup.com/scene/1-test">Watch scene</a>
            <p>Scene advertising, not the synopsis.</p></td></tr></table>""",
        )
        result = colt.parse_group(doc, GROUP_URL)
        self.assertEqual(
            result["synopsis"],
            "Compilation synopsis.\n\nA second paragraph.\n\nDVD SKU: MAN-001D",
        )
        self.assertEqual(result["director"], "Rip Colt")
        self.assertEqual(result["duration"], "13200")

    def test_description_without_spec_bullets_is_unchanged(self):
        description = """<p>A complete synopsis.</p><p>Second paragraph.</p>
        <p>- An unusual narrative line.</p><p>A preview of the story.</p>"""
        result = colt.parse_group(group_page(description=description), GROUP_URL)
        self.assertEqual(
            result["synopsis"],
            "A complete synopsis.\n\nSecond paragraph.\n\n"
            "- An unusual narrative line.\n\nA preview of the story.\n\nDVD SKU: MAN-001D",
        )

    def test_narrative_lines_mentioning_spec_words_are_kept(self):
        description = """<p>Synopsis.</p><p>- Director's cut with extra scenes</p>
        <p>- Previews of upcoming titles</p>
        <p>The story ships in a crate to the packaging plant.</p>"""
        result = colt.parse_group(group_page(description=description), GROUP_URL)
        self.assertEqual(
            result["synopsis"],
            "Synopsis.\n\n- Director's cut with extra scenes\n\n"
            "- Previews of upcoming titles\n\n"
            "The story ships in a crate to the packaging plant.\n\nDVD SKU: MAN-001D",
        )

    def test_spec_only_description_keeps_multiple_skus(self):
        for marker in ("-", "•", "●", "◦"):
            with self.subTest(marker=marker):
                doc = group_page(
                    description=f"""<p>{marker} Directed by Rip Colt<br>
                    {marker} TRT of 220 mins on one disc<br>
                    {marker} Region Free<br>{marker} Photo Galleries<br>
                    {marker} Previews</p>""",
                    variants=[{"sku": "A"}, {"sku": "B"}],
                )
                result = colt.parse_group(doc, GROUP_URL)
                self.assertEqual(result["synopsis"], "DVD SKU: A, B")
                self.assertEqual(result["director"], "Rip Colt")
                self.assertEqual(result["duration"], "13200")

    def test_shipping_note_variants_are_removed(self):
        for note in (
            "**Please note the DVD uses wallet packaging.",
            "This DVD ships in our White Label packaging.",
        ):
            with self.subTest(note=note):
                result = colt.parse_group(
                    group_page(description=f"<p>Synopsis.</p><p>{note}</p>"),
                    GROUP_URL,
                )
                self.assertEqual(result["synopsis"], "Synopsis.\n\nDVD SKU: MAN-001D")

    def test_description_label_lines_are_extracted_once(self):
        doc = group_page(
            description="""<p>Brand: Olympus</p>
            <p>Release Date: 2004-05-06</p>"""
        )
        with patch.object(colt, "label_lines", wraps=colt.label_lines) as extract:
            result = colt.parse_group(doc, GROUP_URL)
        extract.assert_called_once()
        self.assertEqual(result["studio"]["name"], "Olympus")
        self.assertEqual(result["date"], "2004-05-06")

    def test_table_cell_synopsis_without_paragraph_wrapper(self):
        doc = group_page(
            description="""<table><tr><td>Compilation synopsis.<br><br>
            - Directed by Rip Colt<br>- TRT of 220 mins on one disc
            <p>Packaging note.</p></td></tr>
            <tr><td><a href="https://www.coltstudiogroup.com/scene/1-test">Watch scene</a></td>
            <td>Not the synopsis</td></tr></table>"""
        )
        result = colt.parse_group(doc, GROUP_URL)
        self.assertIn("Compilation synopsis.", result["synopsis"])
        self.assertNotIn("Not the synopsis", result["synopsis"])
        self.assertEqual(result["director"], "Rip Colt")
        self.assertEqual(result["duration"], "13200")

    def test_dvd_fields(self):
        result = colt.parse_group(group_page(), GROUP_URL)
        self.assertEqual(result["director"], "Jane Director")
        self.assertEqual(result["duration"], "2460")
        self.assertIn("DVD SKU: MAN-001D", result["synopsis"])
        self.assertNotIn("Scene advertising", result["synopsis"])
        self.assertNotIn("date", result)

    def test_content_tags_only(self):
        self.assertEqual(
            colt.parse_group(group_page(), GROUP_URL)["tags"],
            [{"name": "Muscle"}, {"name": "Vintage"}],
        )

    def test_non_dict_variants_are_skipped(self):
        result = colt.parse_group(
            group_page(
                variants=[
                    None,
                    "invalid",
                    123,
                    [],
                    {"sku": "MAN-001D"},
                    {},
                    {"sku": "MAN-002D"},
                    {"sku": "MAN-001D"},
                ]
            ),
            GROUP_URL,
        )
        self.assertTrue(result["synopsis"].endswith("DVD SKU: MAN-001D, MAN-002D"))

    def test_null_images_and_tags_are_empty(self):
        result = colt.parse_group(group_page(images=None, tags=None), GROUP_URL)
        self.assertEqual(result["name"], "Red Hot")
        self.assertNotIn("front_image", result)
        self.assertNotIn("back_image", result)
        self.assertNotIn("tags", result)

    def test_substudio_tag_overrides_umbrella_vendor(self):
        self.assertEqual(
            colt.parse_group(group_page(tags=["Buckshot"]), GROUP_URL)["studio"][
                "name"
            ],
            "Buckshot",
        )

    def test_original_front_not_montage_back(self):
        result = colt.parse_group(group_page(), GROUP_URL)
        self.assertIn("MAN001_F_uuid.jpg", result["front_image"])
        self.assertNotIn("back_image", result)

    def test_explicit_back_cover(self):
        doc = group_page(
            images=[
                "//coltstudiostore.com/cdn/shop/products/title_front.jpg",
                "//coltstudiostore.com/cdn/shop/products/title_back.jpg",
            ]
        )
        self.assertTrue(
            colt.parse_group(doc, GROUP_URL)["back_image"].endswith("title_back.jpg")
        )

    def test_back_cover_is_not_used_as_front_cover(self):
        result = colt.parse_group(
            group_page(images=["//coltstudiostore.com/title_back.jpg"]), GROUP_URL
        )
        self.assertIn("back_image", result)
        self.assertNotIn("front_image", result)

    def test_explicit_release_date(self):
        result = colt.parse_group(
            group_page(description="<p>Release Date: 2004-05-06</p>"), GROUP_URL
        )
        self.assertEqual(result["date"], "2004-05-06")

    def test_year_only_is_not_invented_date(self):
        result = colt.parse_group(
            group_page(description="<p>Release Date: 2004</p>"), GROUP_URL
        )
        self.assertNotIn("date", result)

    def test_non_dvd_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a DVD"):
            colt.parse_group(group_page(type="Calendar"), GROUP_URL)

    def test_related_product_data_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            colt.parse_group(group_page(handle="wrong-product"), GROUP_URL)

    def test_missing_embedded_product_rejected(self):
        with self.assertRaisesRegex(ValueError, "data missing"):
            colt.parse_group(
                html.fromstring("<html><h1>Access denied</h1></html>"), GROUP_URL
            )

    def test_product_json_with_unrelated_trailing_script(self):
        self.assertEqual(colt.product_data(group_page())["handle"], "red-hot")


def profile_page(
    suffix="", cut_label="Cut / Uncut", url=PROFILE_URL, name="Seth Fornea"
):
    return html.fromstring(f"""<html><link rel="canonical" href="{url}">
          <div class="modelProfileSidebar"><div class="profile">
          <img class="img-responsive" src="//static.coltstudiogroup.com/model.jpg">
           <div class="main_title"><h3>{name}</h3><p>A biography.</p>
          <p class="iconsCenter"><a href="/models/tag/111-colt-man">COLT Man</a></p></div>
          <ul><li>Height{suffix} <strong>6′ 00″</strong></li><li>Weight{suffix} <strong>198 pounds</strong></li>
          <li>Dick size{suffix} <strong>8.50 inches</strong></li><li>{cut_label}{suffix} <strong>Cut</strong></li>
          <li>Position{suffix} <strong>Top</strong></li></ul>
           </div></div></html>""")


def scene_profile_pages(dvd=False, extras=""):
    pages = {
        SCENE_URL: scene_page(dvd=dvd, extras=extras),
        HOT_COP_URL: profile_page(url=HOT_COP_URL, name="Hot Cop"),
        PROFILE_URL: profile_page(),
    }
    if dvd:
        pages[GROUP_URL] = group_page()
    return pages


def test_movie_core_fields_reuse_one_product_parse_and_group():
    doc = group_page(
        description="""<p>DVD synopsis.</p><p>- Directed by Jane Director<br>
        - TRT of 41 mins</p><p>Release Date: 2004-05-06</p>""",
        variants=[{"sku": "MAN-001D"}, {"sku": "MAN-002D"}, {"sku": "MAN-001D"}],
    )
    with (
        patch.object(colt, "product_data", wraps=colt.product_data) as parse,
        patch("builtins.print") as output,
    ):
        result = colt.scrape("movie", GROUP_URL, lambda url: doc)
    parse.assert_called_once_with(doc)
    output.assert_not_called()
    group = colt.parse_group(doc, GROUP_URL)
    assert result == {
        "title": "Red Hot",
        "urls": [GROUP_URL],
        "groups": [group],
        "studio": group["studio"],
        "director": "Jane Director",
        "date": "2004-05-06",
        "tags": [{"name": "Muscle"}, {"name": "Vintage"}],
        "details": "DVD synopsis.\n\nRelease Date: 2004-05-06",
        "code": "MAN-001D, MAN-002D",
        "image": group["front_image"],
        "performers": [],
    }
    assert group["synopsis"].endswith("DVD SKU: MAN-001D, MAN-002D")
    assert group["duration"] == "2460"
    assert "duration" not in result


def test_movie_without_optional_fields_or_scene_links_needs_one_request():
    doc = group_page(
        description="<p>Featuring Someone Famous.</p>",
        variants=[],
        tags=[],
        images=[],
    )
    calls = []

    def fetch(url):
        calls.append(url)
        return doc

    result = colt.scrape("movie", GROUP_URL, fetch)
    assert calls == [GROUP_URL]
    assert result["performers"] == []
    assert result["details"] == "Featuring Someone Famous."
    for key in ("code", "date", "image", "tags", "director", "duration"):
        assert key not in result


def movie_pages():
    pages = scene_profile_pages(dvd=True)
    second_url = colt.SITE + "/scene/396-red-hot-scene-2"
    second = scene_page(performers=False)
    second.xpath('//link[@rel="canonical"]')[0].set("href", second_url)
    second.xpath(colt.DETAILS)[0].append(
        html.fromstring("""<div>
        <span class="perfImage"><a href="/profile/334-other-slug">Seth Alias</a></span>
        <span class="perfImage"><a href="/profile/999-new-credit">New Credit</a></span>
        </div>""")
    )
    pages[second_url] = second
    pages[colt.SITE + "/profile/999-new-credit"] = profile_page(
        url=colt.SITE + "/profile/999-new-credit", name="Different Profile Name"
    )
    pages[GROUP_URL] = group_page(
        description=f"""<table>
        <tr><td>DVD synopsis.</td></tr>
        <tr><td><a href="{SCENE_URL}">Scene 1</a>Promotion 1</td></tr>
        <tr><td><a href="{second_url}">Scene 2</a>Promotion 2</td></tr>
        <tr><td><a href="{SCENE_URL}">Duplicate</a></td></tr></table>"""
    )
    return pages, second_url


def test_movie_performer_union_deduplicates_profile_ids_in_first_seen_order():
    pages, second_url = movie_pages()
    calls = []

    def fetch(url):
        calls.append(url)
        return pages[url]

    result = colt.scrape("movie", GROUP_URL, fetch)
    new_profile = colt.SITE + "/profile/999-new-credit"
    assert calls == [
        GROUP_URL,
        SCENE_URL,
        second_url,
        HOT_COP_URL,
        PROFILE_URL,
        new_profile,
    ]
    assert [p["name"] for p in result["performers"]] == [
        "Hot Cop",
        "Seth Fornea",
        "New Credit",
    ]
    assert all(p["height"] == "183" for p in result["performers"])
    assert result["performers"][1]["urls"] == [PROFILE_URL]
    assert result["details"] == "DVD synopsis."
    assert result["groups"] == [colt.parse_group(pages[GROUP_URL], GROUP_URL)]


@pytest.mark.parametrize("failed_kind", ["scene", "profile"])
@pytest.mark.parametrize("parse_failure", [False, True])
def test_movie_failed_secondary_lookup_keeps_result_and_continues(
    failed_kind, parse_failure, capsys
):
    pages, second_url = movie_pages()
    failed_url = SCENE_URL if failed_kind == "scene" else HOT_COP_URL
    calls = []

    def fetch(url):
        calls.append(url)
        if url == failed_url:
            if parse_failure:
                return html.fromstring("<html><h1>Access denied</h1></html>")
            raise HTTPError(url, 429, "Too Many Requests", {}, None)
        # The second scene uses a slug variant when the first scene fails.
        if url == colt.SITE + "/profile/334-other-slug":
            return pages[PROFILE_URL]
        return pages[url]

    result = colt.scrape("movie", GROUP_URL, fetch)
    assert result["title"] == "Red Hot"
    assert result["groups"][0]["name"] == "Red Hot"
    assert second_url in calls
    assert calls.count(failed_url) == 1
    assert result["performers"][-1]["name"] == "New Credit"
    assert result["performers"][-1]["height"] == "183"
    if failed_kind == "profile":
        assert result["performers"][0] == {"name": "Hot Cop", "urls": [HOT_COP_URL]}
    else:
        assert [p["name"] for p in result["performers"]] == ["Seth Alias", "New Credit"]
    captured = capsys.readouterr()
    assert captured.out == ""
    label = "Scene" if failed_kind == "scene" else "Performer"
    assert f"[Warning] {label} lookup failed for {failed_url}:" in captured.err


def test_scene_links_validate_and_deduplicate_before_promotion_rows_are_removed():
    malformed = SCENE_URL + "%E2%80%9C%20target="
    description = html.fromstring(f"""<div>
        <a href="{malformed}">Malformed</a>
        <a href="http://coltstudiogroup.com/scene/395-red-hot-scene-1?x=1">First</a>
        <a href="{SCENE_URL}">Duplicate</a>
        <a href="https://example.com/scene/1">Foreign</a>
        <a href="/products/red-hot">Product</a>
        <a href="{PROFILE_URL}">Profile</a></div>""")
    assert colt.scene_links(description, GROUP_URL) == [malformed]
    assert colt.page_url(malformed, "scene") == malformed
    assert colt.canonical(scene_page(), malformed, "scene") == SCENE_URL
    pages = {
        GROUP_URL: group_page(description=html.tostring(description).decode()),
        SCENE_URL: scene_page(),
        malformed: scene_page(),
        HOT_COP_URL: profile_page(url=HOT_COP_URL, name="Hot Cop"),
        PROFILE_URL: profile_page(),
    }
    result = colt.scrape("movie", GROUP_URL, pages.__getitem__)
    assert [p["name"] for p in result["performers"]] == ["Hot Cop", "Seth Fornea"]


@pytest.mark.parametrize("kind", sorted(colt.STORE_KINDS))
def test_store_modes_share_url_validation_and_full_canonical_equality(kind):
    assert (
        colt.page_url("http://www.coltstudiostore.com/products/red-hot/?x=1", kind)
        == GROUP_URL
    )
    assert colt.canonical(group_page(), GROUP_URL, kind) == GROUP_URL
    # These handles share a prefix, unlike numeric scene/profile identifiers.
    doc = group_page()
    doc.xpath('//link[@rel="canonical"]')[0].set(
        "href", colt.STORE + "/products/red-other"
    )
    with pytest.raises(ValueError, match="different item"):
        colt.canonical(doc, GROUP_URL, kind)
    for url in (SCENE_URL, colt.STORE + "/collections/dvd/products/red-hot"):
        with pytest.raises(ValueError, match="DVD product URL"):
            colt.page_url(url, kind)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"type": "Calendar"}, "not a DVD"),
        ({"handle": "other-product"}, "does not match"),
    ],
)
def test_movie_rejects_invalid_products(changes, message):
    with pytest.raises(ValueError, match=message):
        colt.scrape("movie", GROUP_URL, lambda url: group_page(**changes))


def test_movie_rejects_wrong_canonical_and_non_store_url():
    doc = group_page()
    doc.xpath('//link[@rel="canonical"]')[0].set(
        "href", colt.STORE + "/products/red-other"
    )
    with pytest.raises(ValueError, match="different item"):
        colt.scrape("movie", GROUP_URL, lambda url: doc)
    with patch.object(colt, "fetch_page") as fetch:
        with pytest.raises(ValueError, match="DVD product URL"):
            colt.scrape("movie", SCENE_URL, fetch)
    fetch.assert_not_called()


def test_main_accepts_movie_and_returns_one_json_value(capsys):
    expected = {"title": "Red Hot", "performers": []}
    with (
        patch.object(sys, "argv", ["coltstudio.py", "movie"]),
        patch.object(sys, "stdin", io.StringIO(json.dumps({"url": GROUP_URL}))),
        patch.object(colt, "scrape", return_value=expected) as scrape,
    ):
        assert colt.main() == 0
    scrape.assert_called_once_with("movie", GROUP_URL)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == expected
    assert captured.err == ""


def test_usage_error_includes_movie(capsys):
    with patch.object(sys, "argv", ["coltstudio.py", "invalid"]):
        assert colt.main() == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) is None
    assert "movie" in captured.err


def test_scene_performers_include_all_profile_fields_before_dvd_lookup():
    pages = scene_profile_pages(dvd=True)
    calls = []

    def fetch(url):
        calls.append(url)
        return pages[url]

    result = colt.scrape("scene", SCENE_URL, fetch)
    assert calls == [SCENE_URL, HOT_COP_URL, PROFILE_URL, GROUP_URL]
    assert result["groups"][0]["name"] == "Red Hot"
    for performer, url in zip(result["performers"], [HOT_COP_URL, PROFILE_URL]):
        assert performer == colt.parse_performer(pages[url], url)
        assert performer["gender"] == "MALE"
        assert performer["height"] == "183"
        assert performer["weight"] == "90"
        assert performer["penis_length"] == "21.59"
        assert performer["circumcised"] == "CUT"
        assert performer["details"] == "A biography."
        assert performer["tags"] == [{"name": "COLT Man"}, {"name": "Top"}]
        assert performer["images"] == ["https://static.coltstudiogroup.com/model.jpg"]


@pytest.mark.parametrize("name", ["SETH FORNEA", "  Seth   Fornea  ", "Different Name"])
def test_scene_credit_name_takes_precedence_over_profile_heading(name):
    pages = scene_profile_pages()
    pages[PROFILE_URL] = profile_page(name=name)
    result = colt.scrape("scene", SCENE_URL, pages.__getitem__)
    assert result["performers"][1]["name"] == "Seth Fornea"
    assert result["performers"][1]["height"] == "183"


@pytest.mark.parametrize(
    "error",
    [
        HTTPError(HOT_COP_URL, 429, "Too Many Requests", {}, None),
        colt.URLError("Unavailable"),
        TypeError("Unexpected type"),
        AttributeError("Unexpected shape"),
        OSError("Connection failed"),
        colt.etree.LxmlError("Invalid document"),
        None,
    ],
)
def test_failed_profile_keeps_minimal_credit_and_continues(error, capsys):
    pages = scene_profile_pages(dvd=True)
    pages[HOT_COP_URL] = html.fromstring("<html><h1>Access denied</h1></html>")

    def fetch(url):
        if url == HOT_COP_URL and error is not None:
            raise error
        return pages[url]

    result = colt.scrape("scene", SCENE_URL, fetch)
    assert result["title"] == "RED HOT Scene 1"
    assert result["performers"][0] == {"name": "Hot Cop", "urls": [HOT_COP_URL]}
    assert result["performers"][1]["height"] == "183"
    assert result["groups"][0]["name"] == "Red Hot"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"[Warning] Performer lookup failed for {HOT_COP_URL}:" in captured.err
    message = str(error) if error is not None else "Performer name missing"
    assert message in captured.err


def test_duplicate_scene_credit_is_fetched_once():
    pages = scene_profile_pages(
        extras='<span class="perfImage"><a href="/profile/334-seth-fornea">Seth Fornea</a></span>'
    )
    calls = []

    def fetch(url):
        calls.append(url)
        return pages[url]

    result = colt.scrape("scene", SCENE_URL, fetch)
    assert calls == [SCENE_URL, HOT_COP_URL, PROFILE_URL]
    assert len(result["performers"]) == 2


def test_same_profile_id_with_different_text_or_slug_is_one_performer():
    pages = scene_profile_pages(
        extras=(
            '<span class="perfImage"><a href="/profile/334">Seth F.</a></span>'
            '<span class="perfImage"><a href="/profile/334-other-slug">Seth</a></span>'
        )
    )
    calls = []

    def fetch(url):
        calls.append(url)
        return pages[url]

    result = colt.scrape("scene", SCENE_URL, fetch)
    assert [p["name"] for p in result["performers"]] == ["Hot Cop", "Seth Fornea"]
    assert calls == [SCENE_URL, HOT_COP_URL, PROFILE_URL]


@pytest.mark.parametrize("canonical_url", [PROFILE_URL, colt.SITE + "/profile/334"])
def test_profile_urls_are_merged_uniquely_with_scene_url_first(canonical_url):
    pages = scene_profile_pages()
    doc = pages[PROFILE_URL]
    doc.xpath('//link[@rel="canonical"]')[0].set("href", canonical_url)
    social_url = "https://www.instagram.com/sethfornea/"
    for _ in range(2):
        doc.xpath(colt.SIDEBAR)[0].append(
            html.fromstring(f'<a href="{social_url}">Instagram</a>')
        )
    result = colt.scrape("scene", SCENE_URL, pages.__getitem__)
    assert result["performers"][1]["urls"] == list(
        dict.fromkeys([PROFILE_URL, canonical_url, social_url])
    )


class PerformerTests(unittest.TestCase):
    def test_profile_fields_and_unit_conversions(self):
        expected = colt.parse_performer(profile_page(), PROFILE_URL)
        for suffix in ("", ":", " :", "  :  "):
            with self.subTest(suffix=suffix):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    result = colt.parse_performer(profile_page(suffix), PROFILE_URL)
                self.assertEqual(result, expected)
                self.assertEqual(result["name"], "Seth Fornea")
                self.assertEqual(result["height"], "183")
                self.assertEqual(result["weight"], "90")
                self.assertEqual(result["penis_length"], "21.59")
                self.assertEqual(result["circumcised"], "CUT")
                self.assertNotIn("birthdate", result)
                self.assertEqual(
                    result["tags"], [{"name": "COLT Man"}, {"name": "Top"}]
                )
                self.assertEqual(stderr.getvalue(), "")

    def test_cut_label_variants(self):
        for label in ("Cut / Uncut", "Cut/Uncut", "Cut", "  CUT /   UNCUT  "):
            with self.subTest(label=label):
                result = colt.parse_performer(
                    profile_page(suffix=" :", cut_label=label), PROFILE_URL
                )
                self.assertEqual(result["circumcised"], "CUT")

    def test_unrecognized_labels_warn_on_stderr(self):
        for label, value in (
            ("Circumcised", "Cut"),
            ("Haircut", "Cut"),
        ):
            with self.subTest(label=label):
                doc = profile_page(cut_label=label)
                doc.xpath(colt.SIDEBAR + "//li/strong")[3].text = value
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    result = colt.parse_performer(doc, PROFILE_URL)
                self.assertNotIn("circumcised", result)
                self.assertNotIn("birthdate", result)
                self.assertEqual(result["height"], "183")
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("[Warning]", stderr.getvalue())
                self.assertIn(label.casefold(), stderr.getvalue())

    def test_age_and_sign_are_ignored_silently(self):
        for label, value in (("Age", "24"), ("Sign", "Gemini")):
            with self.subTest(label=label):
                doc = profile_page(cut_label=label)
                doc.xpath(colt.SIDEBAR + "//li/strong")[3].text = value
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    result = colt.parse_performer(doc, PROFILE_URL)
                self.assertNotIn("circumcised", result)
                self.assertEqual(result["height"], "183")
                self.assertEqual(stderr.getvalue(), "")


class InterfaceTests(unittest.TestCase):
    def test_url_normalization(self):
        self.assertEqual(
            colt.page_url(
                "http://www.coltstudiostore.com/products/red-hot?variant=1",
                "group",
            ),
            GROUP_URL,
        )

    def test_collection_path_group_url_is_rejected(self):
        with self.assertRaises(ValueError):
            colt.page_url(
                "https://coltstudiostore.com/collections/dvd/products/red-hot",
                "group",
            )

    def test_disallowed_urls(self):
        for url in [
            "file:///etc/passwd",
            "https://example.com/scene/1",
            "https://coltstudiogroup.com.evil.com/scene/1",
            "https://user:pass@coltstudiogroup.com/scene/1",
            "https://coltstudiogroup.com:9999/scene/1",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                colt.page_url(url)

    def test_config_routes_and_script_exist(self):
        config = yaml.safe_load((ROOT / "ColtStudio.yml").read_text())
        for key, mode in [
            ("sceneByURL", "scene"),
            ("groupByURL", "group"),
            ("performerByURL", "performer"),
        ]:
            route = config[key][0]
            self.assertEqual(route["action"], "script")
            self.assertEqual(route["script"], ["python", "coltstudio.py", mode])
            self.assertTrue((ROOT / route["script"][1]).is_file())
        movie = config["sceneByURL"][1]
        self.assertEqual(movie["action"], "script")
        self.assertEqual(movie["url"], ["coltstudiostore.com/products/"])
        self.assertEqual(movie["script"], ["python", "coltstudio.py", "movie"])

    def test_bad_input_is_json_null_and_nonzero_exit(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "coltstudio.py"), "scene"],
            check=False,
            input="{}",
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(json.loads(result.stdout))
        self.assertIn("[Error]", result.stderr)

    def test_failed_lxml_install_is_json_null_and_nonzero_exit(self):
        # Block imports and fake pip failure so the test stays offline.
        code = (
            "import runpy, sys, subprocess; from unittest.mock import patch; "
            "sys.modules['lxml'] = None; "
            "patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'pip')).start(); "
            f"runpy.run_path({str(ROOT / 'coltstudio.py')!r}, run_name='__main__')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            input="{}",
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(json.loads(result.stdout))
        self.assertIn("lxml", result.stderr)
        self.assertIn("-m pip install --target", result.stderr)


if __name__ == "__main__":
    unittest.main()
