from typing import Any

type JsonObject = dict[str, Any]
type ColumnSchemaEntry = dict[str, Any]
type ColumnSchema = dict[str, ColumnSchemaEntry]
type ColumnTypeSpec = str | ColumnSchemaEntry
type DatasetRowInput = dict[str, Any]
type SerializedObject = dict[str, Any]
