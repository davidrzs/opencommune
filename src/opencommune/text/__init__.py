"""The text of each page: the PDF's own text layer, and OCR for the pages without one.

1. `layer`: the pages of chosen section types and what PyMuPDF reads on each: the PDF's text, its
   number of characters and how much of the page an image covers.
2. `queue`: the pages chosen for OCR, cut into chunks on a shared file system. Any number of
   workers claim chunks at once, on different machines and graphics cards.
3. `ocr`: one OCR worker. It renders the pages of the chunks it claims, sends them to a vLLM server
   running LightOnOCR-3, many at a time, and appends each answer to its chunk's result file.

`opencommune text` runs them; passes and queues live in DATA_DIR/text. A worker needs a vLLM server
with LightOnOCR-3 on a GPU next to it. Page text can name people, so it stays in DATA_DIR and is
never published as it is.
"""
