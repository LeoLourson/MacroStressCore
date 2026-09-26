import os
from io import BytesIO
from pathlib import Path

from msa.contracts.document import Table


def parse(data: bytes, *, name="document.pdf", converter=None):
    if converter is None:
        try:
            from docling.datamodel.base_models import DocumentStream, InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise RuntimeError("PDF/DOCX ingest requires the docling extra") from exc
        artifacts = os.getenv("MSA_DOCLING_ARTIFACTS_PATH")
        if name.lower().endswith(".pdf") and (not artifacts or not Path(artifacts).is_dir()):
            raise RuntimeError("Set MSA_DOCLING_ARTIFACTS_PATH to local Docling model artifacts")
        options = PdfPipelineOptions(do_ocr=True, do_table_structure=True, artifacts_path=artifacts)
        options.table_structure_options.mode = TableFormerMode.ACCURATE
        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
        )
        source = DocumentStream(name=name, stream=BytesIO(data))
    else:
        source = data
    result = converter.convert(source, max_file_size=20 * 1024 * 1024)
    if result.document is None:
        raise ValueError("Docling did not produce a document")
    return result.document


def tables_to_json(doc) -> list[Table]:
    from docling_core.types.doc import TableItem

    indices = {}
    tables = []
    for item, _ in doc.iterate_items(traverse_pictures=True):
        if not isinstance(item, TableItem):
            continue
        page = item.prov[0].page_no if item.prov else 1
        indices[page] = indices.get(page, 0) + 1
        frame = item.export_to_dataframe(doc=doc)
        cells = [list(map(str, frame.columns))]
        cells += [[str(value) for value in row] for row in frame.itertuples(index=False, name=None)]
        tables.append(Table(page=page, index=indices[page], cells=cells))
    return tables
