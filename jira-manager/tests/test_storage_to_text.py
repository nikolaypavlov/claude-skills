"""Tests for storage_to_text, the read-only plain-text rendering of storage XHTML.

The cases mirror markup seen on a real Confluence Data Center 8.5 instance:
pretty-printed tables with <p> inside cells, page links without their own
text, and code macros with a language parameter.
"""

import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from confluence_client import storage_to_text


class StorageToTextTest(unittest.TestCase):
    def test_inline_markup_stays_on_its_line(self):
        text = storage_to_text(
            "<p>Created by <strong>tool</strong> &amp; <em>friends</em>.</p>"
        )
        self.assertEqual(text, "Created by tool & friends.")

    def test_pretty_printed_table_row_is_one_line(self):
        storage = (
            "<table>\n<tbody>\n<tr>\n<th>Field</th>\n<th>Value</th>\n</tr>\n"
            "<tr>\n<td><p>Status</p></td>\n<td><p>Draft</p>\n<p>for review</p></td>\n</tr>\n"
            "</tbody>\n</table>"
        )
        self.assertEqual(
            storage_to_text(storage), "Field | Value\nStatus | Draft for review"
        )

    def test_page_link_without_text_shows_page_title(self):
        storage = (
            '<p>See <ac:link><ri:page ri:content-title="Runbook" ri:space-key="DOC" /></ac:link> and '
            '<ac:link><ri:page ri:content-title="Other" /><ac:plain-text-link-body><![CDATA[6.0]]>'
            "</ac:plain-text-link-body></ac:link>.</p>"
        )
        self.assertEqual(storage_to_text(storage), "See Runbook and 6.0.")

    def test_code_macro_keeps_code_drops_parameters(self):
        storage = (
            '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">bash</ac:parameter>'
            "<ac:plain-text-body><![CDATA[echo one\necho two]]></ac:plain-text-body></ac:structured-macro>"
        )
        self.assertEqual(storage_to_text(storage), "echo one\necho two")

    def test_blocks_and_list_items_are_separate_lines(self):
        storage = "<h1>Title</h1><p>a<br/>b</p><ul><li>one</li><li>two</li></ul>"
        self.assertEqual(storage_to_text(storage), "Title\na\nb\none\ntwo")

    def test_empty_body(self):
        self.assertEqual(storage_to_text(""), "")


if __name__ == "__main__":
    unittest.main()
