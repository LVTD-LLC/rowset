type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type ColumnSchemaEntry = JsonObject
type ColumnSchema = dict[str, ColumnSchemaEntry]
type ColumnTypeSpec = str | ColumnSchemaEntry
type DatasetRowInput = dict[str, object]
