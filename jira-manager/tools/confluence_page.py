#!/usr/bin/env python3
import argparse
import json
import os
import sys

from confluence_client import ConfluenceManager


def print_page_line(i: int, page: dict) -> None:
    print(f"{i}. [{page['id']}] {page['title']}")
    print(
        f"   Space: {page['space']} | Version: {page['version']} | Updated: {page['updated']}"
    )
    if page.get("excerpt"):
        print(f"   {page['excerpt'][:200]}")
    print(f"   URL: {page['url']}")
    print()


def print_page(page: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(page, ensure_ascii=False, indent=2))
        return
    print("=" * 80)
    print(f"ID: {page['id']}")
    print(f"Title: {page['title']}")
    print(f"Space: {page['space']}")
    print(f"Version: {page['version']}")
    print(f"Updated: {page['updated']} by {page['updated_by']}")
    if page.get("parent_id"):
        print(f"Parent: {page['parent_id']}")
    print(f"URL: {page['url']}")
    if "body" in page:
        print()
        print("Body:")
        print("-" * 80)
        print(page["body"])
        print("-" * 80)
    print("=" * 80)


def read_body(path: str | None) -> str | None:
    """Read a storage-format body from a file, or from stdin when path is '-'"""
    if path is None:
        return None
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def main():
    """Main entry point for confluence_page CLI"""
    parser = argparse.ArgumentParser(
        description="Read, search, create and update Confluence Server / Data Center pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Check the token:
    python confluence_page.py --test

  Read a page (plain text, for reading only):
    python confluence_page.py --get 123456
    python confluence_page.py --space DOC --title "Runbook"

  Read a page in storage format (XHTML, the only safe base for an update):
    python confluence_page.py --get 123456 --format storage --json

  Search with CQL:
    python confluence_page.py --search 'space = DOC AND text ~ "kafka"'

  List child pages:
    python confluence_page.py --children 123456

  Create a page (body is storage XHTML from a file, or '-' for stdin):
    python confluence_page.py --create --space DOC --title "New page" --parent 123456 --body-file page.xhtml

  Update a page (whole body is replaced; guard against concurrent edits):
    python confluence_page.py --update 123456 --body-file page.xhtml --expected-version 7 --message "Fix typo"
        """,
    )

    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--test", action="store_true", help="Check that the token authenticates"
    )
    action.add_argument("--get", type=str, metavar="PAGE_ID", help="Get a page by ID")
    action.add_argument(
        "--search", type=str, metavar="CQL", help="Search content with a CQL query"
    )
    action.add_argument(
        "--children", type=str, metavar="PAGE_ID", help="List direct child pages"
    )
    action.add_argument(
        "--create",
        action="store_true",
        help="Create a page (needs --space, --title, --body-file)",
    )
    action.add_argument(
        "--update",
        type=str,
        metavar="PAGE_ID",
        help="Update a page (needs --body-file and/or --title)",
    )

    parser.add_argument(
        "--space",
        type=str,
        help="Space key (with --title to find a page, or with --create)",
    )
    parser.add_argument("--title", type=str, help="Page title")
    parser.add_argument(
        "--parent", type=str, metavar="PAGE_ID", help="Parent page ID for --create"
    )
    parser.add_argument(
        "--body-file",
        type=str,
        help="File with storage-format (XHTML) body, '-' for stdin",
    )
    parser.add_argument("--message", type=str, help="Version comment for --update")
    parser.add_argument(
        "--expected-version",
        type=int,
        help="Refuse --update if the page is not at this version",
    )
    parser.add_argument(
        "--minor", action="store_true", help="Minor edit (no watcher notifications)"
    )
    parser.add_argument(
        "--format",
        choices=["text", "storage"],
        default="text",
        help="Body format for reads (default: text)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=25,
        help="Maximum search results (default: 25)",
    )
    parser.add_argument("--json", action="store_true", help="Print the page as JSON")

    args = parser.parse_args()

    actions = [
        args.test,
        args.get,
        args.search,
        args.children,
        args.create,
        args.update,
    ]
    find_by_title = not any(actions) and bool(args.space and args.title)
    if not any(actions) and not find_by_title:
        parser.error("one action is required (or --space with --title to find a page)")

    if args.create and not (args.space and args.title and args.body_file):
        parser.error("--create requires --space, --title and --body-file")
    if args.update and not (args.body_file or args.title):
        parser.error("--update requires --body-file and/or --title")

    server_url = os.environ.get("CONFLUENCE_SERVER_URL")
    pat = os.environ.get("CONFLUENCE_API_KEY")

    if not server_url or not pat:
        error_msg = """
ENVIRONMENT VARIABLES REQUIRED

Confluence support requires environment variables to be set:

Missing variables:
"""
        if not server_url:
            error_msg += "  - CONFLUENCE_SERVER_URL (e.g., https://wiki.example.com)\n"
        if not pat:
            error_msg += (
                "  - CONFLUENCE_API_KEY (Personal Access Token created in Confluence)\n"
            )

        error_msg += """
ACTION FOR CLAUDE CODE:
Ask the user to set these environment variables, then run this tool again.

Example:
  export CONFLUENCE_SERVER_URL="https://wiki.example.com"
  export CONFLUENCE_API_KEY="your-confluence-personal-access-token"

WHY:
- CONFLUENCE_SERVER_URL: URL of your Confluence Server / Data Center instance
- CONFLUENCE_API_KEY: Personal Access Token (Confluence 7.9+). A Jira token does
  not work: Server / Data Center tokens are issued per product.
"""
        print(error_msg)
        sys.exit(1)

    confluence = ConfluenceManager(server_url, pat)

    if args.test:
        success, message = confluence.test_connection()
        print(message)

    elif args.get or find_by_title:
        if args.get:
            success, message, page = confluence.get_page(args.get, args.format)
        else:
            success, message, page = confluence.find_page(
                args.space, args.title, args.format
            )
        if success and page:
            print_page(page, args.json)
        else:
            print(f"Failed: {message}")

    elif args.search:
        print(f"Searching: {args.search}")
        print()
        success, message, results = confluence.search(args.search, args.max_results)
        if success:
            print(message)
            print("=" * 80)
            for i, page in enumerate(results, 1):
                print_page_line(i, page)
        else:
            print(f"Failed: {message}")

    elif args.children:
        success, message, children = confluence.get_children(args.children)
        if success:
            print(message)
            print("=" * 80)
            for i, page in enumerate(children, 1):
                print_page_line(i, page)
        else:
            print(f"Failed: {message}")

    elif args.create:
        success, message, page = confluence.create_page(
            args.space, args.title, read_body(args.body_file), args.parent
        )
        print(
            f"Success: {message}\nURL: {page['url']}"
            if success and page
            else f"Failed: {message}"
        )

    else:
        success, message, page = confluence.update_page(
            args.update,
            body=read_body(args.body_file),
            title=args.title,
            version_comment=args.message,
            expected_version=args.expected_version,
            minor_edit=args.minor,
        )
        print(
            f"Success: {message}\nURL: {page['url']}"
            if success and page
            else f"Failed: {message}"
        )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
