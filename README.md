# Stash scrapers

Site-specific scrapers for [Stash](https://stashapp.cc/).
Each scraper has a dedicated folder with its configuration, code, tests, and installation instructions.

- [Colt Studio](scrapers/coltstudio/README.md): scenes, DVD groups, and performers.

## Install

Stash needs Python 3.10 or later with `pip` available inside its runtime or container.
The first scrape installs missing Python dependencies automatically and needs network access.

1. Open Settings → Metadata Providers → Available Scrapers → Add Source in Stash.
2. Choose a source name and local path. Neither value needs a specific name.
3. Enter this source URL: <https://razputingh.github.io/stash-scrapers/index.yml>.
4. Install *Colt Studio*. Stash also installs the required `scraper_deps` package.

## Development

Run the offline tests and build the downloadable packages from the repository root:

```sh
uv run pytest
uv run scripts/build_site.py _site
```

The build writes `index.yml` and one zip per package into `_site/`.
Package versions and dates come from the last git commit for each package directory.
Commit new package directories before building them.
Pushes to `main` test the code and publish the source through GitHub Pages.
