"""Document classification: what kind of document each PDF is, and which parts it has.

A language model sees the pages as images and answers in a fixed JSON form. Requests go to OpenAI's
Batch API with `store: false`; uploaded files are deleted once their results are stored.

1. `record`: the prompt records. Each is versioned by a hash of its files.
2. `render`: page images and request lines, one process per document.
3. `batch_api`: the Batch API.
4. `store`: answers, failures and job state in the processing database.
5. `jobs`: prepare, drive, status, and the import of the first implementation's ledgers.

Answers can name people, so they stay in DATA_DIR and are never published as they are.
"""
