## From source to chunks

`api/v1/endpoints/documents.py` accepts uploads and source import requests. `services/documents.py` validates and records uploads, stores originals and schedules work. Import jobs in `workers/source_ingest.py` normalize supported remote and ZIP content before handing it to the indexing pipeline. GitHub import targets public repositories and is subject to outbound URL and redirect checks. Notion imports are exports uploaded as ZIP files, rather than a live workspace sync.

`workers/extraction.py` extracts text and metadata. PDF pages with too little embedded text can be rendered and passed to `workers/ocr.py` for Tesseract OCR. For native operation the binary and the configured language pack need to be installed on the worker host. DOCX and Markdown extraction can preserve headings. Scans and weak source metadata can produce incomplete headings or OCR errors.

### Chunk structure

`workers/chunking.py` provides fixed windows, paragraph packing, and heading-aware chunking. Auto mode chooses heading-aware packing when structural information is available. The chunk carries text, order, approximate token count, optional page and heading path. This metadata is used in prompt building and citation displays.

### Progress and durability

| Stage | What the UI can report |
| --- | --- |
| Upload | Bytes transferred by the browser |
| Queued and extracting | Current job state and pages as reported by the extractor |
| Chunking and embedding | Chunk totals and completed embedding work once counts are available |
| Indexing and ready | Indexing progress and final page/chunk counts |

Progress is staged, so percentage reflects work reported for the current snapshot. Page totals depend on the format and the information available to the worker. The app makes the recorded failure visible when extraction, storage, embeddings or indexing fail.

## Embeddings and vector indexing

`providers/embeddings.py` embeds batches under the selected profile. `services/qdrant_index.py` synchronizes vector points using the profile dimension, source identifiers and filter metadata. PostgreSQL keeps chunk text and relationships and can retain compatible vectors for the pgvector path. The worker records synchronization state so failures can be diagnosed and repaired. Qdrant is a rebuildable search index, with original bytes and canonical metadata stored separately.
