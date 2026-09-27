"""Validate built documentation links and, optionally, render every Mermaid diagram."""

from __future__ import annotations

import argparse
import functools
import threading
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


class Page(HTMLParser):
    """Collect links and anchors from generated HTML without third-party parsers."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.home_links: list[str] = []
        self.diagrams = 0
        self.canonical = ""
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("data-md-component") == "logo":
            self.home_links.append(values.get("href") or "")
        if tag == "link" and values.get("rel") == "canonical":
            self.canonical = values.get("href") or ""
        if anchor := values.get("id"):
            self.ids.add(anchor)
        if tag == "a" and (anchor := values.get("name")):
            self.ids.add(anchor)
        if "mermaid" in (values.get("class") or "").split():
            self.diagrams += 1
        for attr in ("href", "src"):
            if value := values.get(attr):
                self.links.append(value)


def check_links(site: Path, pages: dict[Path, Page]) -> list[str]:
    errors = []
    prefix = urlsplit(pages[site / "index.html"].canonical).path.rstrip("/")
    for path, page in pages.items():
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                if link in page.home_links:
                    errors.append(f"Logo must link to the documentation home: {path.relative_to(site)}: {link}")
                continue
            local_path = unquote(url.path)
            if prefix and (local_path == prefix or local_path.startswith(prefix + "/")):
                local_path = local_path[len(prefix) :] or "/"
            target = (
                (site / local_path.lstrip("/"))
                if local_path.startswith("/")
                else (path.parent / local_path if local_path else path)
            ).resolve()
            if target.is_dir():
                target /= "index.html"
            label = f"{path.relative_to(site)}: {link}"
            if link in page.home_links and target != site / "index.html":
                errors.append(f"Logo must link to the documentation home: {label}")
            if not target.is_relative_to(site) or not target.is_file():
                errors.append(f"Missing local target: {label}")
            elif url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                errors.append(f"Missing fragment: {label}")
    return sorted(set(errors))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def check_browser(site: Path, pages: dict[Path, Page]) -> list[str]:
    # Optional tooling stays outside the framework's runtime dependencies.
    from playwright.sync_api import Error, sync_playwright  # noqa: PLC0415

    errors = []
    handler = functools.partial(QuietHandler, directory=str(site))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    total = 0
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            # Material renders Mermaid into closed shadow roots. Retain references
            # for inspection without changing shadow mode or the rendering path.
            page.add_init_script("""
                window.docsShadowRoots = new WeakMap();
                const attach = Element.prototype.attachShadow;
                Element.prototype.attachShadow = function(options) {
                    const root = attach.call(this, options);
                    window.docsShadowRoots.set(this, root);
                    return root;
                };
            """)
            for path, document in pages.items():
                if not document.diagrams:
                    continue
                relative = path.relative_to(site).as_posix()
                page.goto(f"http://127.0.0.1:{server.server_port}/{quote(relative)}", wait_until="domcontentloaded")
                try:
                    page.wait_for_function(
                        """count => [...document.querySelectorAll('.mermaid')].length === count &&
                        [...document.querySelectorAll('.mermaid')].every(node =>
                        (window.docsShadowRoots.get(node) || node).querySelector('svg'))""",
                        arg=document.diagrams,
                        timeout=60_000,
                    )
                    states = page.locator(".mermaid").evaluate_all("""nodes => nodes.map(node => {
                        const root = window.docsShadowRoots.get(node) || node;
                        return {
                            error: !!root.querySelector('.error-icon, .error-text'),
                            viewBox: root.querySelector('svg')?.getAttribute('viewBox')
                        };
                    })""")
                    for index, state in enumerate(states, 1):
                        if state["error"]:
                            errors.append(f"Mermaid syntax error: {relative} diagram {index}")
                        if not state["viewBox"]:
                            errors.append(f"Mermaid SVG has no viewBox: {relative} diagram {index}")
                    controls = page.locator(".ff-diagram-toggle")
                    if controls.count() != document.diagrams:
                        errors.append(f"Missing diagram expand controls: {relative}")
                    else:
                        for width in (1440, 390):
                            page.set_viewport_size({"width": width, "height": 1000})
                            button = controls.first
                            button.focus()
                            button.press("Enter")
                            expanded = page.locator(".ff-diagram-scroll").first.evaluate(
                                "node => node.scrollWidth > node.clientWidth"
                            )
                            if button.get_attribute("aria-expanded") != "true" or not expanded:
                                errors.append(f"Diagram did not expand at {width}px: {relative}")
                            button.press("Enter")
                            if button.get_attribute("aria-expanded") != "false":
                                errors.append(f"Diagram did not collapse at {width}px: {relative}")
                        page.set_viewport_size({"width": 1440, "height": 1000})
                    total += document.diagrams
                    print(f"Rendered {document.diagrams:2} diagrams: {relative}", flush=True)
                except Error as exc:
                    errors.append(f"Mermaid rendering failed: {relative}: {exc}")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    print(f"Browser checked {total} Mermaid diagrams.")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, default=Path("site"))
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    site = args.site_dir.resolve()
    pages = {path: Page(path) for path in sorted(site.rglob("*.html"))}
    if not pages:
        parser.error(f"No built HTML found in {site}; run mkdocs build --strict first.")
    errors = check_links(site, pages)
    print(f"Checked {len(pages)} HTML pages and {sum(len(page.links) for page in pages.values())} links.")
    if args.browser:
        errors.extend(check_browser(site, pages))
    if errors:
        raise SystemExit("\n".join(errors))
    print("Documentation checks passed.")


if __name__ == "__main__":
    main()
