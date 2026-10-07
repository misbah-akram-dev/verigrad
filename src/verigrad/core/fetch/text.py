"""HTML → whole-page text. Keeps hidden text on purpose; `visible_text.txt` is the seen view."""

import hashlib

from selectolax.lexbor import LexborHTMLParser

_DROP_TAGS = ["script", "style", "noscript", "template", "svg", "iframe", "object"]
_BLOCK_TAGS = (
    "address, article, aside, blockquote, caption, dd, details, dialog, div, dl, dt, fieldset, "
    "figcaption, figure, footer, form, h1, h2, h3, h4, h5, h6, header, hr, li, main, nav, ol, "
    "p, pre, section, summary, table, tbody, thead, tfoot, tr, ul"
)


def html_to_text(html: str) -> str:
    """One line per block element; table cells separated by ` | `; whitespace normalised."""
    tree = LexborHTMLParser(html)
    tree.strip_tags(_DROP_TAGS)
    for node in tree.css(_BLOCK_TAGS):
        node.insert_before("\n")
        node.insert_after("\n")
    for node in tree.css("td, th"):
        node.insert_after(" | ")
    for node in tree.css("br"):
        node.insert_after("\n")
    root = tree.body or tree.root
    raw = root.text(separator="", strip=False) if root is not None else ""
    return normalise_lines(raw)


def normalise_lines(text: str) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line.strip(" |") for line in lines if line.strip(" |"))


def page_title(html: str) -> str:
    node = LexborHTMLParser(html).css_first("title")
    return " ".join(node.text().split()) if node is not None else ""


def content_hash(text: str) -> str:
    """Stable across markup changes and nonces: hash of whitespace-collapsed text."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()
