"""Offline regression tests. Fixtures model the public Colt page structure."""

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError

import yaml
from lxml import html

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coltstudio", ROOT / "coltstudio.py")
colt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(colt)

SCENE_URL = colt.SITE + "/scene/395-red-hot-scene-1"
GROUP_URL = colt.STORE + "/products/red-hot"
PROFILE_URL = colt.SITE + "/profile/334-seth-fornea"
PHOTO = "https://static.coltstudiogroup.com/_thumbs/a/scn_395_full.jpg"
THUMB = "https://static.coltstudiogroup.com/_thumbs/b/scn_395_small.jpg"


def scene_page(photo=True, dvd=True, extras=""):
    return html.fromstring(f"""<html><head>
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


class SceneTests(unittest.TestCase):
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
                return scene_page()
            raise HTTPError(url, 429, "Too Many Requests", {}, None)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = colt.scrape("scene", SCENE_URL, fetch)
        self.assertEqual(result["title"], "RED HOT Scene 1")
        self.assertNotIn("groups", result)
        self.assertIn("429", stderr.getvalue())

    def test_scene_returns_linked_group(self):
        pages = {SCENE_URL: scene_page(), GROUP_URL: group_page(tags=["Buckshot"])}
        result = colt.scrape("scene", SCENE_URL, pages.__getitem__)
        self.assertEqual(result["groups"][0]["name"], "Red Hot")
        self.assertEqual(result["studio"]["name"], "Buckshot")
        self.assertNotIn("scene_index", result["groups"][0])

    def test_scene_without_dvd_needs_one_request(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return scene_page(dvd=False)

        self.assertNotIn("groups", colt.scrape("scene", SCENE_URL, fetch))
        self.assertEqual(calls, [SCENE_URL])

    def test_explicit_scene_studio_takes_precedence(self):
        for name in ("Colt Studio Group", "Olympus"):
            with self.subTest(name=name):
                pages = {
                    SCENE_URL: scene_page(extras=f"<h5>Studio: {name}</h5>"),
                    GROUP_URL: group_page(tags=["Buckshot"]),
                }
                result = colt.scrape("scene", SCENE_URL, pages.__getitem__)
                self.assertEqual(result["studio"]["name"], name)

    def test_wrong_canonical_is_rejected(self):
        doc = scene_page()
        doc.xpath('//link[@rel="canonical"]')[0].set(
            "href", colt.SITE + "/scene/999-other"
        )
        with self.assertRaises(ValueError):
            colt.parse_scene(doc, SCENE_URL)


class GroupTests(unittest.TestCase):
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


class PerformerTests(unittest.TestCase):
    def test_profile_fields_and_unit_conversions(self):
        doc = html.fromstring(f"""<html><link rel="canonical" href="{PROFILE_URL}">
          <div class="modelProfileSidebar"><div class="profile">
          <img class="img-responsive" src="//static.coltstudiogroup.com/model.jpg">
          <div class="main_title"><h3>Seth Fornea</h3><p>A biography.</p>
          <p class="iconsCenter"><a href="/models/tag/111-colt-man">COLT Man</a></p></div>
          <ul><li>Height <strong>6′ 00″</strong></li><li>Weight <strong>198 pounds</strong></li>
          <li>Dick size <strong>8.50 inches</strong></li><li>Cut / Uncut <strong>Cut</strong></li>
          <li>Position <strong>Top</strong></li><li>Age <strong>24</strong></li></ul>
          </div></div></html>""")
        result = colt.parse_performer(doc, PROFILE_URL)
        self.assertEqual(result["name"], "Seth Fornea")
        self.assertEqual(result["height"], "183")
        self.assertEqual(result["weight"], "90")
        self.assertEqual(result["penis_length"], "21.59")
        self.assertEqual(result["circumcised"], "CUT")
        self.assertNotIn("birthdate", result)
        self.assertEqual(result["tags"], [{"name": "COLT Man"}, {"name": "Top"}])


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

    def test_missing_lxml_is_json_null_and_nonzero_exit(self):
        # A None entry in sys.modules makes `import lxml` raise ModuleNotFoundError.
        code = (
            "import runpy, sys; sys.modules['lxml'] = None; "
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


if __name__ == "__main__":
    unittest.main()
