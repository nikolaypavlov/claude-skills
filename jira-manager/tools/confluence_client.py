"""Confluence Server / Data Center API client using Personal Access Tokens.

Every public method returns a tuple whose first two items are
(success: bool, message: str), the same contract as JiraManager.

Page bodies are read and written in Confluence *storage* representation
(XHTML with ac:/ri: macro elements). An update replaces the whole body, so
callers that edit a page must start from the storage body returned by
get_page(..., body_format="storage"), never from the plain-text rendering:

    get_page(id, "storage") --> edit XHTML --> update_page(id, body=...)
    get_page(id, "text")    --> read only (macros are lost)
"""

from typing import Any

from atlassian import ConfluenceServer
from atlassian.errors import ApiError
from bs4 import BeautifulSoup, CData
from requests import HTTPError, RequestException

BODY_FORMATS = ("text", "storage")
_PAGE_EXPAND = "space,version,ancestors,body.storage"
# Errors the library raises for API / transport failures; ValueError covers a non-JSON reply
_API_ERRORS = (ApiError, RequestException, ValueError)
_APPEARANCE = "content-appearance-published"


_BLOCK_TAGS = {
    "p", "div", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "table", "tbody", "thead", "tr", "hr",
    "ac:structured-macro", "ac:plain-text-body", "ac:rich-text-body",
}  # fmt: skip
_CELL_TAGS = {"td", "th"}
# Macro configuration, not page content (e.g. the language of a code block)
_DROP_TAGS = {"ac:parameter"}


def storage_to_text(storage: str) -> str:
    """Render storage XHTML as plain text for reading.

    Block elements start a new line, table cells on one row are joined with
    " | ", inline markup (<strong>, <a>, ...) stays inside its line, a link to
    another page without its own text shows the page title. Macro parameters
    are dropped, macro text content (e.g. code blocks) is kept.
    The result is lossy and must never be written back to a page.
    """
    soup = BeautifulSoup(storage or "", "html.parser")
    # Source newlines are formatting, not content (storage is often pretty-printed);
    # code blocks (CDATA) keep theirs.
    for node in soup.find_all(string=True):
        if not isinstance(node, CData) and "\n" in node:
            node.replace_with(node.replace("\n", " "))
    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()
    # A link to another page without its own text shows that page's title
    for link in soup.find_all("ac:link"):
        if not link.get_text(strip=True):
            target = link.find(["ri:page", "ri:attachment", "ri:user"])
            label = target and (
                target.get("ri:content-title")
                or target.get("ri:filename")
                or target.get("ri:username")
            )
            if label:
                link.append(label)
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        if tag.name not in ("table", "tbody", "thead", "tr") and tag.find_parent(
            _CELL_TAGS
        ):
            continue  # keep a table cell on one line
        tag.insert_before("\n")
        tag.insert_after("\n")
    for tag in soup.find_all(_CELL_TAGS):
        if tag.find_previous_sibling(_CELL_TAGS) is not None:
            tag.insert_before(" | ")
    lines = (" ".join(line.split()) for line in soup.get_text().splitlines())
    return "\n".join(line for line in lines if line)


def _error_message(e: Exception) -> str:
    if isinstance(e, HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}: {e.response.text[:500]}"
    return str(e)


class ConfluenceManager:
    """Manages Confluence Server / Data Center API interactions"""

    def __init__(self, server_url: str, pat: str):
        """Initialize Confluence client with PAT (Bearer) authentication

        Args:
            server_url: Confluence server URL (e.g., https://wiki.example.com)
            pat: Personal Access Token created in Confluence (Server/DC 7.9+).
                 A Jira PAT does not work here: tokens are issued per product.
        """
        self.server_url = server_url.rstrip("/")
        self.client = ConfluenceServer(url=self.server_url, token=pat)

    def page_url(self, page: dict[str, Any]) -> str:
        webui = page.get("_links", {}).get("webui")
        if webui:
            return f"{self.server_url}{webui}"
        return f"{self.server_url}/pages/viewpage.action?pageId={page.get('id')}"

    def _summarize(
        self, page: dict[str, Any], body_format: str | None = None
    ) -> dict[str, Any]:
        ancestors = page.get("ancestors") or []
        summary: dict[str, Any] = {
            "id": page.get("id"),
            "title": page.get("title"),
            "type": page.get("type"),
            "space": (page.get("space") or {}).get("key"),
            "version": (page.get("version") or {}).get("number"),
            "updated": (page.get("version") or {}).get("when"),
            "updated_by": ((page.get("version") or {}).get("by") or {}).get(
                "displayName"
            ),
            "parent_id": ancestors[-1].get("id") if ancestors else None,
            "url": self.page_url(page),
        }
        if body_format is not None:
            storage = ((page.get("body") or {}).get("storage") or {}).get("value", "")
            summary["body"] = (
                storage if body_format == "storage" else storage_to_text(storage)
            )
        return summary

    def test_connection(self) -> tuple[bool, str]:
        """Check that the token authenticates (anonymous access does not count)

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            user = self.client.get_current_user()
        except _API_ERRORS as e:
            return False, f"Connection failed: {_error_message(e)}"
        if (
            not isinstance(user, dict)
            or user.get("type") == "anonymous"
            or not user.get("username")
        ):
            return (
                False,
                "Connected, but the token was not accepted (request is anonymous)",
            )
        return True, f"Connected to Confluence as {user.get('username')}"

    def get_page(
        self, page_id: str, body_format: str = "text"
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Get a page by ID

        Args:
            page_id: Confluence content ID
            body_format: "text" (lossy, for reading) or "storage" (XHTML, for editing)

        Returns:
            Tuple of (success: bool, message: str, page: Optional[dict])
        """
        if body_format not in BODY_FORMATS:
            return (
                False,
                f"Unknown body format '{body_format}', use one of {BODY_FORMATS}",
                None,
            )
        try:
            page = self.client.get_page_by_id(page_id, expand=_PAGE_EXPAND)
        except _API_ERRORS as e:
            return False, f"Failed to get page {page_id}: {_error_message(e)}", None
        return True, f"Retrieved page {page_id}", self._summarize(page, body_format)

    def find_page(
        self, space_key: str, title: str, body_format: str = "text"
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Get a page by exact title within a space

        Returns:
            Tuple of (success: bool, message: str, page: Optional[dict])
        """
        try:
            found = self.client.get_page_by_title(space_key, title)
        except _API_ERRORS as e:
            return (
                False,
                f"Failed to find page '{title}' in {space_key}: {_error_message(e)}",
                None,
            )
        results = (found or {}).get("results") or []
        if not results:
            return False, f"No page titled '{title}' in space {space_key}", None
        return self.get_page(results[0]["id"], body_format)

    def search(
        self, cql: str, limit: int = 25
    ) -> tuple[bool, str, list[dict[str, Any]]]:
        """Search content with CQL

        Args:
            cql: CQL query (e.g., 'space = DOC AND text ~ "kafka"')
            limit: Maximum number of results

        Returns:
            Tuple of (success: bool, message: str, results: list[dict])
        """
        try:
            response = self.client.cql(
                cql, limit=limit, expand="content.space,content.version"
            )
        except _API_ERRORS as e:
            return False, f"Search failed: {_error_message(e)}", []
        results = []
        for item in (response or {}).get("results") or []:
            content = item.get("content") or {}
            if not content:
                continue
            page = self._summarize(content)
            excerpt = (
                (item.get("excerpt") or "")
                .replace("@@@hl@@@", "")
                .replace("@@@endhl@@@", "")
            )
            # One line per hit: table cells would otherwise each get their own line
            page["excerpt"] = " ".join(storage_to_text(excerpt).split())
            results.append(page)
        total = (response or {}).get("totalSize", len(results))
        return True, f"Found {total} result(s), showing {len(results)}", results

    def get_children(
        self, page_id: str, limit: int = 200
    ) -> tuple[bool, str, list[dict[str, Any]]]:
        """List direct child pages

        Returns:
            Tuple of (success: bool, message: str, children: list[dict])
        """
        try:
            children = self.client.get_page_child_by_type(
                page_id, type="page", start=0, limit=limit, expand="space,version"
            )
        except _API_ERRORS as e:
            return (
                False,
                f"Failed to list children of {page_id}: {_error_message(e)}",
                [],
            )
        pages = [self._summarize(child) for child in children or []]
        return True, f"Found {len(pages)} child page(s)", pages

    def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        parent_id: str | None = None,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Create a page from a storage-format (XHTML) body

        Returns:
            Tuple of (success: bool, message: str, page: Optional[dict])
        """
        try:
            page = self.client.create_page(
                space=space_key,
                title=title,
                body=body,
                parent_id=parent_id,
                representation="storage",
            )
        except _API_ERRORS as e:
            return False, f"Failed to create page '{title}': {_error_message(e)}", None
        summary = self._summarize(page)
        return True, f"Created page {summary['id']}", summary

    def _is_full_width(self, page_id: str) -> bool:
        """Read the published page width from its content property.

        Uses the property endpoint, not expand=metadata.properties.<key>: on
        Data Center 8.5 that expand returns HTTP 500 when the page has no such
        property, which is the normal case (no property = default fixed width).
        """
        try:
            prop = self.client.get_content_property(page_id, _APPEARANCE)
        except HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return False
            raise
        return (prop or {}).get("value") == "full-width"

    def update_page(
        self,
        page_id: str,
        body: str | None = None,
        title: str | None = None,
        version_comment: str | None = None,
        expected_version: int | None = None,
        minor_edit: bool = False,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Replace the body and/or title of a page

        The body replaces the whole page and must be storage XHTML. Pass
        expected_version (the version you read) to refuse the write when
        someone else has edited the page in the meantime.

        Returns:
            Tuple of (success: bool, message: str, page: Optional[dict])
        """
        if body is None and title is None:
            return False, "Nothing to update: pass a body and/or a title", None
        try:
            current = self.client.get_page_by_id(
                page_id,
                expand="space,ancestors,version,body.storage",
            )
        except _API_ERRORS as e:
            return False, f"Failed to get page {page_id}: {_error_message(e)}", None

        current_version = (current.get("version") or {}).get("number")
        if expected_version is not None and current_version != expected_version:
            return (
                False,
                (
                    f"Page {page_id} is at version {current_version}, expected {expected_version}; "
                    "re-read it and apply the change again"
                ),
                None,
            )

        current_body = ((current.get("body") or {}).get("storage") or {}).get("value")
        if body is None and current_body is None:
            return (
                False,
                f"Page {page_id}: server returned no storage body, refusing a title-only update",
                None,
            )

        new_title = title if title is not None else current.get("title")
        new_body = body if body is not None else current_body
        if new_body == current_body and new_title == current.get("title"):
            return (
                True,
                f"Page {page_id} unchanged (content already up to date)",
                self._summarize(current),
            )

        # The library sends a page width on every update (fixed unless told
        # otherwise), so carry the current setting over. Data Center 8.5 ignores
        # it for existing pages (verified live), other versions may apply it.
        try:
            full_width = self._is_full_width(page_id)
        except _API_ERRORS as e:
            return (
                False,
                f"Failed to read page width of {page_id}: {_error_message(e)}",
                None,
            )

        try:
            page = self.client.update_page(
                page_id=page_id,
                title=new_title,
                # A PUT without a body is not a safe "keep": resend the current one
                body=new_body,
                representation="storage",
                minor_edit=minor_edit,
                version_comment=version_comment,
                full_width=full_width,
                # Change detection is done above; the library's own check returns
                # a page without version info when it skips the write.
                always_update=True,
            )
        except _API_ERRORS as e:
            return False, f"Failed to update page {page_id}: {_error_message(e)}", None
        summary = self._summarize(page)
        return (
            True,
            f"Updated page {page_id} to version {summary.get('version')}",
            summary,
        )
