# Tags Column Type Design

## Goal

Add `tags` as a first-class Rowset semantic column type. Agents and people can
select the type through every supported schema surface while row values remain
plain comma-separated strings in storage, REST, MCP, CLI, filtering, and
exports.

## Product Contract

- `tags` is accepted anywhere Rowset accepts semantic column metadata.
- A tags cell stores and returns its original string without normalization.
- UI rendering splits the string on commas, trims surrounding whitespace, and
  ignores empty or whitespace-only segments.
- Each visible tag renders as a pill. Authenticated views use a deterministic
  color derived from the normalized value only when the profile's existing
  `choice_colorization_enabled` setting is enabled; otherwise pills are neutral.
- Public views use neutral pills because they have no authenticated profile
  preference.
- Editing continues to use the original comma-separated string.
- Tags render consistently in authenticated dataset tables, authenticated row
  details, public preview tables, and public row details.
- Blank or separator-only values use the existing blank-cell presentation.

## Architecture

The dataset domain owns the new semantic type and display parsing. Add `tags`
to `DatasetColumnType`, schema validation, column-definition serialization, and
the supported-type descriptions exposed by REST and MCP. The API and MCP keep
delegating to the shared dataset services so their behavior stays aligned.

The dataset view layer converts a tags cell into a list of display items. Each
item contains the trimmed label and, when profile colorization is enabled, one
deterministic class from the existing choice-pill color palette. This display
metadata is separate from the cell's original value. A shared template partial
renders the list so all four table and row-detail surfaces use the same markup;
neutral styling is the default and is always used for public views.

The CLI continues to transmit row values unchanged. Its schema-facing commands,
help, validation, examples, and tests must recognize `tags` wherever semantic
column types are enumerated.

## Data Flow

1. A user or agent declares a column as `tags` through the UI, REST, MCP, or
   CLI.
2. Shared dataset validation stores `{\"type\": \"tags\"}` in column schema.
3. Row writes preserve the supplied comma-separated string exactly.
4. REST, MCP, CLI reads, search, and exports return that same string.
5. Server-rendered dataset views derive nonblank trimmed labels for display and
   render pills, adding deterministic colors only for authenticated profiles
   that enabled the existing colorization setting.

## Error Handling

`tags` requires no extra metadata and accepts the same cell values as text.
Unknown semantic types continue to fail through the existing validation path.
Malformed non-string stored values use Rowset's existing string conversion
before display parsing.

## Testing

Use outside-in TDD:

- Start with Django integration tests proving all authenticated and public table
  and row-detail surfaces render trimmed pills, omit empty segments, and retain
  the original value for editing.
- Cover colored and neutral authenticated rendering according to the existing
  profile setting, plus neutral public rendering.
- Add focused service tests proving `tags` is accepted and row/API values are
  not transformed.
- Add REST/MCP parity coverage for tags schema metadata and unchanged row data.
- Add CLI tests for schema input/help and unchanged comma-separated values.
- Run focused tests after each red/green slice, then the relevant broader
  dataset, API/MCP, frontend-build, and CLI checks.

## Non-goals

- Structured array storage or API values.
- Escaped commas, quoted CSV parsing, tag autocomplete, tag management, or
  server-side tag filtering semantics.
- Backward-compatibility aliases, redirects, or migrations for unsupported
  historical type names.
