# Colt Studio

A standalone Stash scraper for Colt Studio Group scenes, Colt Store DVDs, and performer profiles.
It does not depend on AdultSiteRunner or the earlier library maintenance scripts.
It makes no changes to your Stash library. You review and apply scrape results in Stash.

## Installation

Stash must have Python 3.10 or later and `lxml` available to its Python executable.
These requirements apply inside the Stash container, not only on your computer.
This scraper targets Stash v0.31.1.

1. Find the scraper directory in Stash under Settings → Metadata Providers → Scrapers.
2. Create a `coltstudio` folder inside that directory.
3. Copy `ColtStudio.yml` and `coltstudio.py` into that folder.
4. Install `lxml>=5,<7` in the Python environment that Stash uses, if it is not already available.
5. Reload the scrapers in Stash.

Stash runs `python coltstudio.py` from the scraper folder.
The inline dependency declaration supports local `uv run` use. Stash itself does not install these dependencies.
For containers, retain the dependency in your container setup so that it survives a rebuild.

AdultSiteRunner also handles Colt scene and performer URLs.
Select Colt Studio explicitly when Stash offers a scraper choice.
If your URL workflow always selects AdultSiteRunner, remove its two `coltstudiogroup.com` URL entries from your installed copy.
A community scraper update can restore those entries. Do not disable AdultSiteRunner if you use it for other sites.

## Supported URLs

Use a scene URL in the scene editor, a DVD URL in the group editor, or a profile URL in the performer editor.
The scraper accepts HTTP and HTTPS, with or without `www`, and normalizes its output to HTTPS.
Only `coltstudiostore.com/products/` URLs work.
Collection-path URLs such as `/collections/dvd/products/title` do not. Remove the `/collections/dvd` part of the address.
Collection listing pages do not work.

Examples:

```text
https://www.coltstudiogroup.com/scene/395-colt-man-seth-fornea-red-hot-scene-1
https://coltstudiostore.com/products/colt-man-seth-fornea-red-hot
https://www.coltstudiogroup.com/profile/334-seth-fornea
```

## Returned metadata

Scene results include the title, Colt scene code, canonical URL, full description, categories as tags, and listed performers with profile URLs.
The image comes from the main scene player, not the `og:image` social thumbnail.
The scraper requires the current scene ID in the image filename and excludes the related-scenes section.
If the main image is absent, it uses the current scene's social thumbnail.
It returns explicit full release dates and directors when the scene page provides them.

Each direct DVD product link in the scene details produces a related group result.
The scraper follows only these links. It does not guess DVD matches from scene titles.
If the store request fails or the DVD is unavailable, it logs a warning and keeps the scene result.
It makes no automatic retries, including after rate-limit responses.

DVD group results include the product title, canonical URL, synopsis, director, runtime in seconds, and artwork when available.
DVD SKUs remain in the synopsis because Stash groups have no code field.
The scraper uses original product images and recognizes front/back covers by filename markers.
It uses the first product image as the front cover when no front marker exists.
It does not assume that the second product image is a back cover. Store images often include montages or packaging photos.
Product content tags are retained, but brand, DVD, sale, inventory, and merchandising labels are excluded.
Explicit categories or tags in the DVD description are also retained.

Performer results include the name, profile URL, male gender, image, biography, profile tags, and social links when available.
Height, weight, and penis length use centimeters, kilograms, and centimeters respectively.
Circumcision status and position tags are retained when listed.
The scraper does not derive a birth date from the displayed age.
It returns performer credits as listed, without name-specific exceptions.

## Studios and dates

An explicit scene studio label takes precedence over the DVD label.
Otherwise, the DVD vendor, label, or brand tags can identify a Colt-family studio.
Recognized specific labels are Buckshot, Olympus, and Minute Man.
COLT and COLT Studio map to Colt Studio Group. Unidentified labels also use Colt Studio Group.
Titles and narrative descriptions do not determine the studio.

The scraper accepts full dates only. It does not turn a release year into January 1.
Shopify `created_at` and `published_at` describe store records, not film releases, and are never used as release dates.
A DVD release date does not become a scene release date.

Stash v0.31.1 has no scene-index field in its scraped-group format.
Group results therefore do not set scene order, even when a scene title includes a number.
Scraping returns group suggestions. It does not bulk-create groups or attach scenes without your review.
Scrape the DVD URL in the group editor to retrieve its artwork directly.

## Development and tests

From this folder, run the offline tests:

```sh
uv run --group dev python -m unittest discover -s tests -v
```

To scrape a public scene without contacting your Stash server:

```sh
echo '{"url":"https://www.coltstudiogroup.com/scene/395-colt-man-seth-fornea-red-hot-scene-1"}' | uv run coltstudio.py scene
```

Replace `scene` with `group` or `performer` for the other URL types.
The helper writes one JSON value to standard output and warnings/errors to standard error.
On a failed primary scrape, it returns JSON `null` and exits with status 1.
Tests use synthetic HTML fixtures based on the public page structure. They make no network requests.

Live checks on October 30, 2026 returned the main scene photo at 1280×720 and the social thumbnail at 640×360.
The same check returned the linked Red Hot DVD with director Kristofer Weston, a 41-minute runtime, and its front cover.
Local results contain image URLs. Stash downloads the images during scrape post-processing.

## References

The community [AdultSiteRunner scraper](https://github.com/stashapp/CommunityScrapers/blob/master/scrapers/AdultSiteRunner.yml) provided the comparison for existing coverage and page structure.
This implementation uses its own parser and DVD lookups.
The [Stash scraper development guide](https://github.com/stashapp/stash/blob/v0.31.1/ui/v2.5/src/docs/en/Manual/ScraperDevelopment.md) describes the script input/output contract.
