import os
import re
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, build_opener

from msa.contracts import SourceDocument
from msa.contracts.document import Fragment
from msa.integrations.docling.parse import parse, tables_to_json
from msa.storage.originals import OriginalStore


def fragment(text: str, locator: str) -> Fragment:
    return Fragment(locator=locator, text=text, sha256=sha256(text.encode("utf-8")).hexdigest())


class IngestAgent:
    def __init__(self, store=None, *, downloader=None, converter=None):
        self.store = store or OriginalStore()
        self.downloader = downloader or self._download
        self.converter = converter

    @staticmethod
    def _download(url):
        parsed = urlparse(url)
        hosts = set(filter(None, os.getenv("MSA_INGEST_URL_HOSTS", "").split(",")))
        if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username:
            raise ValueError("URL host must be explicitly allowed by MSA_INGEST_URL_HOSTS")

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                return None

        with build_opener(NoRedirect).open(url, timeout=20) as response:
            data = response.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("Document exceeds 20 MiB")
        return data

    def run(self, payload: dict) -> SourceDocument:
        if "url" in payload:
            data = self.downloader(payload["url"])
            name = Path(urlparse(payload["url"]).path).name
        elif "bytes" in payload:
            data = payload["bytes"]
            name = payload.get("name", "document.pdf")
        elif "text" in payload:
            data = payload["text"].encode("utf-8")
            name = payload.get("name", "event.txt")
        else:
            raise ValueError("Expected text, bytes or URL")
        if not isinstance(data, bytes):
            raise TypeError("Document content must be bytes")
        digest = self.store.put(data)
        suffix = Path(name).suffix.lower()
        if suffix in {".pdf", ".docx"}:
            mime = (
                "application/pdf"
                if suffix == ".pdf"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            doc = parse(data, name=name, converter=self.converter)
            tables = tables_to_json(doc)
            fragments = []
            para_count = {}
            table_count = {}
            from docling_core.types.doc import TableItem, TextItem

            for item, _ in doc.iterate_items(traverse_pictures=True):
                page = item.prov[0].page_no if item.prov else 1
                if isinstance(item, TableItem):
                    table_count[page] = table_count.get(page, 0) + 1
                    table = next(
                        t for t in tables if t.page == page and t.index == table_count[page]
                    )
                    for row_index, row in enumerate(table.cells, 1):
                        for col_index, value in enumerate(row, 1):
                            if value.strip():
                                locator = f"p{page}/t{table.index}/r{row_index}c{col_index}"
                                fragments.append(fragment(value, locator))
                elif isinstance(item, TextItem) and item.text.strip():
                    para_count[page] = para_count.get(page, 0) + 1
                    fragments.append(fragment(item.text, f"p{page}/para{para_count[page]}"))
        else:
            mime = "text/plain"
            text = data.decode("utf-8")
            parts = [part for part in re.split(r"\n\s*\n", text) if part.strip()]
            fragments = [fragment(part, f"p1/para{i}") for i, part in enumerate(parts, 1)]
            tables = []
        return SourceDocument(
            doc_id=digest,
            sha256=digest,
            mime=mime,
            fragments=fragments,
            tables=tables,
            status="parsed" if fragments or tables else "unparsed",
        )
