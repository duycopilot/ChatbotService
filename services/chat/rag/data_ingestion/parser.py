"""Build LangChain document nodes from passage CSV rows and flattened table chunks."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from langchain_core.documents import Document


DEFAULT_TEXT_PASSAGES_CSV = Path("/home/leo/workspace/ChatbotService/data/raw_files/passage.csv")
DEFAULT_TABLES_DIR = Path("/home/leo/workspace/ChatbotService/data/temp_files/flatten_tables")
LEGACY_TEXT_PASSAGES_CSV = Path("/home/leo/workspace/ChatbotService/data/temp_files/content.csv")
LEGACY_TABLES_JSON = Path("/home/leo/workspace/ChatbotService/data/temp_files/individual_flatten_table.json")


def _clean_text(value: object) -> str:
	if value is None:
		return ""
	return str(value).strip()


def _to_int(value: object) -> int | None:
	raw = _clean_text(value)
	if not raw:
		return None
	try:
		return int(raw)
	except ValueError:
		return None


def _normalize_content_type(value: str, source_type: str = "text") -> str:
	lowered = value.strip().lower()
	if source_type == "table":
		return "Table"

	if not lowered:
		return "definition"

	mapping = {
		"definition": "definition",
		"diagnostic_criteria": "Diagnostic_criteria",
		"recommendation": "Recommendation",
		"treatment_protocol": "Treatment_protocol",
		"drug_info": "Drug_info",
		"warning": "Warning",
		"table": "Table",
		"special_population": "Special_population",
		"summary": "summary",
	}
	return mapping.get(lowered, value)


def _build_header_path(title: str, h1: str, h2: str, h3: str, h4: str) -> str:
	parts = [title, h1, h2, h3, h4]
	return " > ".join(part for part in parts if _clean_text(part))


def _read_csv_rows(csv_path: Path) -> list[dict[str, Any]]:
	with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
		return [dict(row) for row in csv.DictReader(csv_file)]


def _get_row_value(row: dict[str, Any], *keys: str) -> str:
	for key in keys:
		if key in row and _clean_text(row.get(key)):
			return _clean_text(row.get(key))
	return ""


def _load_text_passages(csv_path: Path) -> tuple[list[Document], dict[str, dict[str, Any]]]:
	nodes: list[Document] = []
	table_context_by_file: dict[str, dict[str, Any]] = {}

	rows = _read_csv_rows(csv_path)
	for index, row in enumerate(rows):
		content = _get_row_value(row, "content", "Content")
		if not content:
			continue

		title = _get_row_value(row, "title", "Title")
		h1 = _get_row_value(row, "header1", "header_1", "Section")
		h2 = _get_row_value(row, "header2", "header_2")
		h3 = _get_row_value(row, "header3", "header_3")
		h4 = _get_row_value(row, "header4", "header_4")
		page = _to_int(_get_row_value(row, "page", "Page"))
		doc_id = _get_row_value(row, "id", "ID") or f"{csv_path.stem}:{index + 1}"
		content_type = _normalize_content_type(_get_row_value(row, "content_type", "Type"))
		ref = _get_row_value(row, "ref", "Ref")
		linked_file = _get_row_value(row, "file", "File")

		metadata = {
			"doc_id": doc_id,
			"source": str(csv_path),
			"source_file": csv_path.name,
			"source_type": "text_row",
			"page": page,
			"title": title,
			"h1": h1,
			"h2": h2,
			"h3": h3,
			"h4": h4,
			"header_path": _build_header_path(title, h1, h2, h3, h4),
			"paragraph_order": len(nodes),
			"content_type": content_type,
			"ref": ref,
			"file": linked_file,
		}
		nodes.append(
			Document(
				page_content=content,
				metadata={k: v for k, v in metadata.items() if v not in (None, "")},
			)
		)

		if linked_file:
			context_payload = {
				"doc_id": doc_id,
				"title": title,
				"h1": h1,
				"h2": h2,
				"h3": h3,
				"h4": h4,
			}
			table_context_by_file[linked_file] = context_payload
			table_context_by_file[Path(linked_file).stem] = context_payload

	return nodes, table_context_by_file


def _iter_table_files(tables_path: Path) -> list[Path]:
	if tables_path.is_file():
		return [tables_path]
	if tables_path.is_dir():
		return sorted(path for path in tables_path.glob("*.json") if path.is_file())
	return []


def _load_table_rows_from_file(json_path: Path) -> list[dict[str, Any]]:
	with json_path.open("r", encoding="utf-8") as json_file:
		payload = json.load(json_file)

	if isinstance(payload, list):
		return [item for item in payload if isinstance(item, dict)]
	if isinstance(payload, dict):
		return [payload]
	return []


def _load_tables(
	tables_path: Path,
	*,
	table_context_by_file: dict[str, dict[str, Any]] | None = None,
	start_paragraph_order: int = 0,
) -> list[Document]:
	nodes: list[Document] = []
	paragraph_order = start_paragraph_order
	table_context_by_file = table_context_by_file or {}

	for table_file in _iter_table_files(tables_path):
		rows = _load_table_rows_from_file(table_file)
		inherited = table_context_by_file.get(table_file.name) or table_context_by_file.get(table_file.stem) or {}

		for row in rows:
			table_name = _clean_text(row.get("table_name"))
			row_content = _clean_text(row.get("row_content") or row.get("rows"))
			if not row_content:
				continue

			structured = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}

			title = _clean_text(structured.get("title") or inherited.get("title"))
			h1 = _clean_text(structured.get("h1") or inherited.get("h1"))
			h2 = _clean_text(structured.get("h2") or inherited.get("h2"))
			h3 = _clean_text(structured.get("h3") or inherited.get("h3"))
			h4 = _clean_text(structured.get("h4") or inherited.get("h4"))
			page = _to_int(structured.get("source_page") or structured.get("page"))
			doc_id = _clean_text(structured.get("doc_id") or inherited.get("doc_id"))
			content_type = _normalize_content_type(_clean_text(structured.get("content_type")), source_type="table")

			metadata: dict[str, Any] = {
				"doc_id": doc_id or f"table:{table_file.stem}",
				"source": str(table_file),
				"source_file": _clean_text(structured.get("source_file")) or table_file.name,
				"source_type": "table_row",
				"page": page,
				"title": title,
				"h1": h1,
				"h2": h2,
				"h3": h3,
				"h4": h4,
				"header_path": _build_header_path(title, h1, h2, h3, h4),
				"paragraph_order": paragraph_order,
				"content_type": content_type,
				"table_name": table_name,
				"table_group": _clean_text(structured.get("table_group")),
				"chunk_role": _clean_text(structured.get("chunk_role")),
				"file": table_file.name,
			}

			nodes.append(
				Document(
					page_content=row_content,
					metadata={k: v for k, v in metadata.items() if v not in (None, "")},
				)
			)
			paragraph_order += 1

	return nodes


# Backward-compatible aliases for existing imports/usages.
_load_main_content = _load_text_passages
_load_flatten_tables = _load_tables


def ingest_documents(
	text_passages_csv_path: str | Path = DEFAULT_TEXT_PASSAGES_CSV,
	tables_json_path: str | Path = DEFAULT_TABLES_DIR,
	*,
	content_csv_path: str | Path | None = None,
	flatten_table_json_path: str | Path | None = None,
) -> list[Document]:
	"""Load parsed files and convert them to LangChain document nodes."""
	csv_path = Path(content_csv_path) if content_csv_path is not None else Path(text_passages_csv_path)
	json_path = (
		Path(flatten_table_json_path)
		if flatten_table_json_path is not None
		else Path(tables_json_path)
	)

	if not csv_path.exists() and csv_path == DEFAULT_TEXT_PASSAGES_CSV and LEGACY_TEXT_PASSAGES_CSV.exists():
		csv_path = LEGACY_TEXT_PASSAGES_CSV

	if not json_path.exists() and json_path == DEFAULT_TABLES_DIR and LEGACY_TABLES_JSON.exists():
		json_path = LEGACY_TABLES_JSON

	if not csv_path.exists():
		raise FileNotFoundError(f"Text passages CSV not found: {csv_path}")
	if not json_path.exists():
		raise FileNotFoundError(f"Tables path not found: {json_path}")

	text_documents, table_context = _load_text_passages(csv_path)
	table_documents = _load_tables(
		json_path,
		table_context_by_file=table_context,
		start_paragraph_order=len(text_documents),
	)

	documents = [*text_documents, *table_documents]
	return documents


if __name__ == "__main__":
	docs = ingest_documents()
	payload = [{"page_content": doc.page_content, "metadata": doc.metadata} for doc in docs]
	with Path("/home/duynt/Refined_Chatbot/parsed_content.json").open(
		"w", encoding="utf-8"
	) as output_file:
		json.dump(payload, output_file, ensure_ascii=False, indent=2)

	print(f"Created {len(docs)} LangChain nodes")
