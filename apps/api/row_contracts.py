from collections.abc import Iterable, Mapping
from typing import Literal, Required, TypedDict

RowCellValue = object
RowWritePayload = Mapping[str, RowCellValue]
RowData = dict[str, str]
RowFilters = dict[str, str]
RowFilterOperators = dict[str, str]
RowSearchSource = Literal["hybrid", "vector", "lexical"]


class RowSearchCandidate(TypedDict, total=False):
    row_id: Required[int]
    vector_rank: int
    vector_score: float
    point_id: str
    chunk_index: int | None
    content_hash: str | None
    lexical_rank: int


class RankedRowSearchCandidate(RowSearchCandidate):
    score: Required[float]
    source: Required[RowSearchSource]


def stringify_row_cell(value: RowCellValue) -> str:
    if value is None:
        return ""
    return str(value)


def normalize_row_data_for_headers(data: RowWritePayload, headers: Iterable[str]) -> RowData:
    return {header: stringify_row_cell(data.get(header, "")) for header in headers}


def normalize_row_patch_for_headers(data: RowWritePayload, headers: Iterable[str]) -> RowData:
    allowed_headers = set(headers)
    return {
        header: stringify_row_cell(value)
        for header, value in data.items()
        if header in allowed_headers
    }


def normalize_search_filters(filters: Mapping[str, RowCellValue] | None) -> RowFilters:
    if filters is None:
        return {}

    normalized_filters: RowFilters = {}
    for raw_header, raw_value in filters.items():
        header = str(raw_header or "").strip()
        if not header:
            raise ValueError("Search filter headers must be non-empty.")
        value = "" if raw_value is None else str(raw_value).strip()
        if value:
            normalized_filters[header] = value
    return normalized_filters


def normalize_search_filter_operators(
    filter_operators: Mapping[str, RowCellValue] | None,
    filters: RowFilters,
) -> RowFilterOperators:
    if filter_operators is None:
        return {}

    normalized_operators: RowFilterOperators = {}
    for raw_header, raw_operator in filter_operators.items():
        header = str(raw_header or "").strip()
        if not header:
            raise ValueError("Search filter operator headers must be non-empty.")
        if header not in filters:
            continue
        operator = str(raw_operator or "").strip().lower()
        if operator:
            normalized_operators[header] = operator
    return normalized_operators
