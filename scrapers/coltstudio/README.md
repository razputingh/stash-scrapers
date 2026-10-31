# Colt Studio

A standalone Stash scraper for Colt Studio Group scenes, Colt Store DVDs, and performer profiles.
It does not depend on AdultSiteRunner or the earlier library maintenance scripts.
It makes no changes to your Stash library. You review and apply scrape results in Stash.

## Installation

Stash must have Python 3.10 or later with `pip` available to its Python executable.
These requirements apply inside the Stash container, not only on your computer.
This scraper targets Stash v0.31.1.

1. Open Settings → Metadata Providers → Available Scrapers → Add Source.
2. Enter <https://razputingh.github.io/stash-scrapers/index.yml> and choose any source name and local path.
3. Install *Colt Studio*. Stash installs `scraper_deps` through the package dependency list.

Stash runs `python coltstudio.py` from the scraper folder.
On the first scrape, `scraper_deps` installs `lxml>=5,<7` automatically if `lxml` is not importable.
This needs network access and a writable scraper source directory.
Dependencies live in `automatic_dependencies/` beside the installed package folders and are shared across the source.
Already importable modules are used without a version check.
If installation fails, the error names the package and the pip command to run with Stash's Python.
The inline dependency declaration also supports local `uv run` use.
For containers, retain the scraper source directory across rebuilds to avoid reinstalling dependencies.

AdultSiteRunner also handles Colt scene and performer URLs.
Select Colt Studio explicitly when Stash offers a scraper choice.
If your URL workflow always selects AdultSiteRunner, remove its two `coltstudiogroup.com` URL entries from your installed copy.
A community scraper update can restore those entries. Do not disable AdultSiteRunner if you use it for other sites.

## Supported URLs

Use a scene URL in the scene editor, a DVD product URL in the scene or group editor, or a profile URL in the performer editor.
In the scene editor, a DVD URL returns the whole film as one scene and includes its DVD group.
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

Scene performers also include the profile fields described below.
The scraper makes one extra request per distinct performer in each scene, before the DVD lookups.
These requests run one at a time, so scenes with more performers take longer.
The scene credit remains the performer's name, even when the profile heading differs.
Profile URLs and social links are combined without duplicates, with the scene's profile URL first.
If a profile request or parse fails, the scraper logs a warning and keeps the performer's name and profile URL.
It keeps the scene and continues with the other performers and DVDs.

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

Whole-film scene results use the DVD title, studio, director, explicit release date, tags, and front cover.
The DVD SKU becomes the scene code. Multiple distinct SKUs are joined with commas.
The scene description excludes the `DVD SKU:` line, but the related group's synopsis keeps it.
The scene result does not set a duration because Stash's scraped-scene format has no duration field.
The related group keeps the DVD runtime.

For whole films, the scraper collects performers from the scene pages linked in the DVD description.
It does not infer names from the “Featuring...” prose.
It makes one extra request per distinct linked scene, then one per distinct performer profile across those scenes.
These requests run one at a time. Credits keep their first-seen order, with duplicates removed by numeric profile ID.
Alternate scene slugs, including malformed store links, are de-duplicated by numeric scene ID before requests.
Failed scene requests log a warning and do not discard the film or later scenes.
Failed profile requests keep the name and profile URL. A DVD without scene links returns an empty performer list.
The DVD product is fetched and parsed only once for both the whole-film scene and its related group.

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
A DVD release date does not become an individual scene's release date.
Whole-film scenes use the DVD's explicit full release date when available.

Stash v0.31.1 has no scene-index field in its scraped-group format.
Group results therefore do not set scene order, even when a scene title includes a number.
Scraping returns group suggestions. It does not bulk-create groups or attach scenes without your review.
Scrape the DVD URL in the group editor to retrieve its artwork directly.

## Development and tests

From this folder, run the offline tests:

```sh
uv run --group dev pytest tests
```

To scrape a public scene without contacting your Stash server:

```sh
echo '{"url":"https://www.coltstudiogroup.com/scene/395-colt-man-seth-fornea-red-hot-scene-1"}' | uv run coltstudio.py scene
```

Replace `scene` with `group` or `performer` for the other URL types.
Use `movie` with a DVD product URL to scrape a whole-film scene:

```sh
echo '{"url":"https://coltstudiostore.com/products/fresh-off-the-vine"}' | uv run coltstudio.py movie
```

The helper writes one JSON value to standard output and warnings/errors to standard error.
On a failed primary scrape, it returns JSON `null` and exits with status 1.
Tests use synthetic HTML fixtures based on the public page structure. They make no network requests.

Live checks on October 30, 2026 returned the main scene photo at 1280×720 and the social thumbnail at 640×360.
The same check returned the linked Red Hot DVD with director Kristofer Weston, a 41-minute runtime, and its front cover.
The public Seth Fornea profile used `Height`, `Weight`, `Dick size`, `Cut / Uncut`, and `Position` without colons, matching the fixture.
The performer check returned 183 cm, 90 kg, 21.59 cm penis length, `CUT`, and a `Top` tag.
Tests also cover labels with colons and extra spaces.
Unrecognized performer labels produce warnings on standard error, including the live profile's unsupported `Age` and `Sign` fields.
Local results contain image URLs. Stash downloads the images during scrape post-processing.

A live whole-film check on October 31, 2026 returned Fresh Off The Vine with code `BSP-020D` and studio Buckshot.
Its group retained the 113-minute runtime. The scene had no duration and no SKU line in its description.
All four linked scenes, including the malformed links, resolved to their expected scene IDs.
The combined credits included eight distinct performers, with Devon Hunter and Topher DiMaggio from Scene 2.
These are suggestions for review, not automatic changes to existing Stash credits.

## References

The community [AdultSiteRunner scraper](https://github.com/stashapp/CommunityScrapers/blob/master/scrapers/AdultSiteRunner.yml) provided the comparison for existing coverage and page structure.
This implementation uses its own parser and DVD lookups.
The [Stash scraper development guide](https://github.com/stashapp/stash/blob/v0.31.1/ui/v2.5/src/docs/en/Manual/ScraperDevelopment.md) describes the script input/output contract.
