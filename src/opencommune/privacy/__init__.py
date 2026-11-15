"""The privacy check: personal data in the text of the pages the search covers.

1. `detect`: the pages to check (those in scope with usable text, opencommune.scope), and one
   worker that runs gheim on the pages of the chunks it claims and records what it finds. The
   chunks of a privacy queue (`text.queue`) carry the text, so a worker needs nothing else.
2. `store`: DATA_DIR/privacy.db, what was found on each page.

Nothing is removed here. What is removed from the text is decided when the index is built, from
what was found, so that decision can change without checking the pages again. A worker needs gheim
(`uv sync --extra privacy`) and, to be fast, a GPU.
"""
