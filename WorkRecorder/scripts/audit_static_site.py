"""Audit the WorkRecorder static site for broken local links and brand drift."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE_DIR = REPO_ROOT / "site" / "dist"
PUBLIC_HTML_GLOB = "*.html"
LEGACY_BRAND = "NorthPrism"
LEGACY_ALLOWED_FILES: set[str] = set()


@dataclass(frozen=True, slots=True)
class SiteFinding:
    """One static-site quality finding.

    Attributes:
        path: Repository-relative file or directory path for the finding.
        code: Stable machine-readable finding code.
        message: Human-readable explanation and suggested fix.
    """

    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SiteAuditReport:
    """Structured output for the static-site audit.

    Attributes:
        site_dir: Absolute static-site directory that was checked.
        checked_files: Number of HTML files inspected.
        findings: Stable sorted audit findings.
    """

    site_dir: str
    checked_files: int
    findings: tuple[SiteFinding, ...]

    @property
    def ok(self) -> bool:
        """Return whether the site passed all checks.

        Returns:
            ``True`` when no static-site findings were collected.
        """

        return not self.findings

    def to_json_text(self) -> str:
        """Serialize the report as stable JSON.

        Returns:
            UTF-8 friendly JSON text suitable for CI artifacts.
        """

        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


class _HtmlAssetParser(HTMLParser):
    """Collect the tiny subset of HTML data needed by the audit.

    Attributes:
        links: Raw href values from anchors.
        assets: Raw src/href values from linkable asset tags.
        ids: HTML element IDs used to detect duplicates.
        title_text: Text fragments seen inside the title tag.
        has_viewport: Whether a viewport meta tag was seen.
        has_lang: Whether the html element declares a language.
    """

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.assets: list[str] = []
        self.ids: list[str] = []
        self.title_text: list[str] = []
        self.has_viewport = False
        self.has_lang = False
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Collect links, assets, IDs, viewport metadata, and title state.

        Args:
            tag: Lowercase HTML tag name from ``HTMLParser``.
            attrs: Raw HTML attributes attached to the tag.
        """

        attr_map = {key.lower(): value for key, value in attrs if value is not None}
        if tag == "html" and attr_map.get("lang"):
            self.has_lang = True
        if tag == "meta" and attr_map.get("name", "").lower() == "viewport":
            self.has_viewport = True
        if tag == "title":
            self._in_title = True
        if "id" in attr_map:
            self.ids.append(attr_map["id"])
        if tag == "a" and "href" in attr_map:
            self.links.append(attr_map["href"])
        for attr in ("src", "href"):
            value = attr_map.get(attr)
            if value and tag in {"script", "link", "img", "source"}:
                self.assets.append(value)

    def handle_endtag(self, tag: str) -> None:
        """Track title parsing state.

        Args:
            tag: Lowercase HTML tag name from ``HTMLParser``.
        """

        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        """Collect title text.

        Args:
            data: Raw text payload emitted by ``HTMLParser``.
        """

        if self._in_title:
            self.title_text.append(data.strip())


def audit_static_site(site_dir: Path = DEFAULT_SITE_DIR) -> SiteAuditReport:
    """Audit HTML pages, local asset references, and brand hygiene.

    Args:
        site_dir: Directory containing the static site.

    Returns:
        Structured audit report.
    """

    findings: list[SiteFinding] = []
    html_files = tuple(sorted(site_dir.rglob(PUBLIC_HTML_GLOB)))
    if not site_dir.exists():
        return SiteAuditReport(
            site_dir=str(site_dir),
            checked_files=0,
            findings=(
                SiteFinding(path=str(site_dir), code="site.missing", message="Static site directory is missing."),
            ),
        )
    if not html_files:
        findings.append(SiteFinding(path=_relative(site_dir), code="site.no_html", message="No HTML files found."))

    for html_file in html_files:
        text = html_file.read_text(encoding="utf-8")
        parser = _HtmlAssetParser()
        parser.feed(text)
        _check_html_document(findings, html_file, text, parser)
        _check_local_references(findings, site_dir, html_file, parser.links, kind="link")
        _check_local_references(findings, site_dir, html_file, parser.assets, kind="asset")
        _check_duplicate_ids(findings, html_file, parser.ids)
        _check_legacy_brand(findings, html_file, text)

    _check_legacy_brand_in_docs(findings, site_dir)
    sorted_findings = tuple(sorted(findings, key=lambda item: (item.path, item.code, item.message)))
    return SiteAuditReport(site_dir=str(site_dir), checked_files=len(html_files), findings=sorted_findings)


def format_report(report: SiteAuditReport) -> str:
    """Format a static-site audit report for terminal output.

    Args:
        report: Structured report returned by ``audit_static_site``.

    Returns:
        Human-readable report text.
    """

    lines = [
        "WorkRecorder static-site audit",
        f"site: {report.site_dir}",
        f"metrics: {report.checked_files} HTML file(s), {len(report.findings)} finding(s)",
    ]
    if report.findings:
        lines.append("")
        lines.append("Findings:")
        lines.extend(f"- {finding.code} {finding.path} - {finding.message}" for finding in report.findings)
    else:
        lines.append("")
        lines.append("No static-site findings.")
    return "\n".join(lines)


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for the static-site audit.

    Returns:
        Configured argument parser.
    """

    parser = argparse.ArgumentParser(description="Check WorkRecorder static site links, assets, and brand hygiene.")
    parser.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)
    parser.add_argument("--json-output", type=Path, default=None)
    return parser


def main() -> int:
    """Run the static-site audit command.

    Returns:
        Process exit status.
    """

    args = build_argument_parser().parse_args()
    report = audit_static_site(args.site_dir)
    print(format_report(report))
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(report.to_json_text(), encoding="utf-8")
    return 0 if report.ok else 1


def _check_html_document(
    findings: list[SiteFinding],
    html_file: Path,
    text: str,
    parser: _HtmlAssetParser,
) -> None:
    if "<!doctype html>" not in text[:128].lower():
        findings.append(
            SiteFinding(path=_relative(html_file), code="html.doctype_missing", message="Add <!doctype html>.")
        )
    if not parser.has_lang:
        findings.append(SiteFinding(path=_relative(html_file), code="html.lang_missing", message="Set <html lang>."))
    if not parser.has_viewport:
        findings.append(
            SiteFinding(
                path=_relative(html_file), code="html.viewport_missing", message="Add responsive viewport meta."
            )
        )
    if not "".join(parser.title_text).strip():
        findings.append(SiteFinding(path=_relative(html_file), code="html.title_missing", message="Add a page title."))


def _check_local_references(
    findings: list[SiteFinding],
    site_dir: Path,
    html_file: Path,
    references: Iterable[str],
    *,
    kind: str,
) -> None:
    for reference in references:
        local_path = _resolve_local_reference(site_dir, html_file, reference)
        if local_path is None:
            continue
        if not local_path.exists():
            findings.append(
                SiteFinding(
                    path=_relative(html_file),
                    code=f"{kind}.missing",
                    message=f"Missing local {kind}: {reference}",
                )
            )
            continue
        fragment = urlparse(reference).fragment
        if fragment and local_path.suffix.lower() == ".html":
            _check_fragment_target(findings, html_file, local_path, reference, fragment)


def _check_duplicate_ids(findings: list[SiteFinding], html_file: Path, ids: Iterable[str]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            duplicates.add(identifier)
        seen.add(identifier)
    for identifier in sorted(duplicates):
        findings.append(
            SiteFinding(path=_relative(html_file), code="html.duplicate_id", message=f"Duplicate id: {identifier}")
        )


def _check_fragment_target(
    findings: list[SiteFinding],
    source_html: Path,
    target_html: Path,
    reference: str,
    fragment: str,
) -> None:
    parser = _HtmlAssetParser()
    parser.feed(target_html.read_text(encoding="utf-8"))
    if fragment not in set(parser.ids):
        findings.append(
            SiteFinding(
                path=_relative(source_html),
                code="link.fragment_missing",
                message=f"Missing fragment target for local link: {reference}",
            )
        )


def _check_legacy_brand(findings: list[SiteFinding], html_file: Path, text: str) -> None:
    if LEGACY_BRAND in text:
        findings.append(
            SiteFinding(
                path=_relative(html_file),
                code="brand.legacy_name",
                message=f"Public HTML should not mention {LEGACY_BRAND}.",
            )
        )


def _check_legacy_brand_in_docs(findings: list[SiteFinding], site_dir: Path) -> None:
    for path in sorted(site_dir.glob("*.md")):
        if path.name in LEGACY_ALLOWED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        if LEGACY_BRAND in text:
            findings.append(
                SiteFinding(
                    path=_relative(path),
                    code="brand.legacy_name",
                    message=f"Site markdown should not mention {LEGACY_BRAND}.",
                )
            )


def _resolve_local_reference(site_dir: Path, html_file: Path, reference: str) -> Path | None:
    parsed = urlparse(reference)
    if parsed.scheme or parsed.netloc or reference.startswith(("mailto:", "tel:", "#")):
        return None
    path_part = unquote(parsed.path)
    if not path_part:
        return None
    if path_part.startswith("/"):
        return (site_dir / path_part.lstrip("/")).resolve()
    return (html_file.parent / path_part).resolve()


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
