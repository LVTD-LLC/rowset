package rowsetcli

import (
	"fmt"
	"io"
	"sort"
	"strings"
)

type helpEntry struct {
	usage   string
	summary string
	example string
}

var commandHelp = map[string]helpEntry{
	"capabilities":            {"rowset capabilities [--topic TOPIC ...] [--include-use-cases] [--full]", "Inspect Rowset's live capability guide.", "rowset capabilities --topic rows --include-use-cases"},
	"healthcheck":             {"rowset healthcheck", "Check whether the Rowset API is reachable.", "rowset healthcheck"},
	"user":                    {"rowset user <command>", "Inspect the authenticated Rowset account.", "rowset user info"},
	"user info":               {"rowset user info", "Return the authenticated Rowset account.", "rowset user info"},
	"feedback":                {"rowset feedback <command>", "Send product feedback to Rowset.", "rowset feedback submit --feedback \"Compact CLI output helps agents\""},
	"feedback submit":         {"rowset feedback submit --feedback TEXT [--page PATH] [--context JSON]", "Send concise product feedback.", "rowset feedback submit --feedback \"Nested help is clear\" --page /docs"},
	"api-key":                 {"rowset api-key <command>", "Manage Rowset API keys.", "rowset api-key create --name Codex"},
	"api-key create":          {"rowset api-key create --name NAME [--access-level read|read_write|admin]", "Create an API key.", "rowset api-key create --name Codex --access-level read_write"},
	"project":                 {"rowset project <command>", "Manage projects and project sections.", "rowset project list --limit 3"},
	"project list":            {"rowset project list [flags]", "List projects.", "rowset project list --query launch --limit 3"},
	"project search":          {"rowset project search QUERY [--limit N] [--offset N]", "Search projects.", "rowset project search \"launch ops\" --limit 3"},
	"project create":          {"rowset project create --name NAME [flags]", "Create a project.", "rowset project create --name \"Launch Ops\""},
	"project get":             {"rowset project get PROJECT_KEY [--limit N] [--offset N]", "Inspect one project.", "rowset project get \"{project_key}\""},
	"project update":          {"rowset project update PROJECT_KEY [--name NAME] [--description TEXT]", "Update a project.", "rowset project update \"{project_key}\" --name \"Launch Ops\""},
	"project metadata":        {"rowset project metadata PROJECT_KEY --metadata JSON", "Replace project metadata.", "rowset project metadata \"{project_key}\" --metadata '{\"owner\":\"ops\"}'"},
	"project archive":         {"rowset project archive PROJECT_KEY", "Archive a project.", "rowset project archive \"{project_key}\""},
	"project section":         {"rowset project section <command>", "Manage sections in a project.", "rowset project section list \"{project_key}\""},
	"project section list":    {"rowset project section list PROJECT_KEY [--limit N] [--offset N]", "List project sections.", "rowset project section list \"{project_key}\""},
	"project section create":  {"rowset project section create PROJECT_KEY --name NAME [flags]", "Create a project section.", "rowset project section create \"{project_key}\" --name Backlog"},
	"project section update":  {"rowset project section update PROJECT_KEY SECTION_KEY [flags]", "Update a project section.", "rowset project section update \"{project_key}\" \"{section_key}\" --name Ready"},
	"project section archive": {"rowset project section archive PROJECT_KEY SECTION_KEY", "Archive a project section.", "rowset project section archive \"{project_key}\" \"{section_key}\""},
	"dataset":                 {"rowset dataset <command>", "Manage datasets and their metadata.", "rowset dataset get \"{dataset_key}\""},
	"dataset list":            {"rowset dataset list [flags]", "List datasets.", "rowset dataset list --limit 3"},
	"dataset search":          {"rowset dataset search QUERY [flags]", "Search datasets.", "rowset dataset search \"launch tasks\" --limit 3"},
	"dataset archived":        {"rowset dataset archived [--limit N] [--offset N]", "List archived datasets.", "rowset dataset archived --limit 3"},
	"dataset get":             {"rowset dataset get DATASET_KEY", "Inspect one dataset.", "rowset dataset get \"{dataset_key}\""},
	"dataset create":          {"rowset dataset create --name NAME [flags]", "Create a dataset.", "rowset dataset create --name Tasks --headers task_id,title --index-column task_id"},
	"dataset metadata":        {"rowset dataset metadata DATASET_KEY [flags]", "Update dataset context.", "rowset dataset metadata \"{dataset_key}\" --description \"Launch tasks\""},
	"dataset column-types":    {"rowset dataset column-types DATASET_KEY --column-types JSON", "Update semantic column types.", "rowset dataset column-types \"{dataset_key}\" --column-types '{\"status\":\"text\"}'"},
	"dataset project":         {"rowset dataset project DATASET_KEY (--project-key KEY [--section-key KEY] | --clear)", "Assign or unassign a dataset project.", "rowset dataset project \"{dataset_key}\" --project-key \"{project_key}\""},
	"dataset archive":         {"rowset dataset archive DATASET_KEY", "Archive a dataset.", "rowset dataset archive \"{dataset_key}\""},
	"dataset restore":         {"rowset dataset restore DATASET_KEY", "Restore an archived dataset.", "rowset dataset restore \"{dataset_key}\""},
	"preview":                 {"rowset preview <command>", "Manage read-only public previews.", "rowset preview update \"{dataset_key}\" --enabled false"},
	"preview update":          {"rowset preview update DATASET_KEY [flags]", "Update public preview settings.", "rowset preview update \"{dataset_key}\" --enabled true --page-size 25"},
	"column":                  {"rowset column <command>", "Manage dataset columns.", "rowset column add \"{dataset_key}\" --name status"},
	"column add":              {"rowset column add DATASET_KEY --name NAME [flags]", "Add a dataset column.", "rowset column add \"{dataset_key}\" --name status --default-value Ready"},
	"column rename":           {"rowset column rename DATASET_KEY OLD_NAME NEW_NAME", "Rename a dataset column.", "rowset column rename \"{dataset_key}\" old_name new_name"},
	"column drop":             {"rowset column drop DATASET_KEY NAME", "Drop a dataset column.", "rowset column drop \"{dataset_key}\" notes"},
	"column reorder":          {"rowset column reorder DATASET_KEY --headers HEADERS", "Reorder dataset columns.", "rowset column reorder \"{dataset_key}\" --headers task_id,title,status"},
	"relationship":            {"rowset relationship <command>", "Manage dataset relationships.", "rowset relationship list \"{dataset_key}\""},
	"relationship list":       {"rowset relationship list DATASET_KEY", "List dataset relationships.", "rowset relationship list \"{dataset_key}\""},
	"relationship create":     {"rowset relationship create DATASET_KEY --source-column COLUMN --target-dataset-key KEY [flags]", "Create a dataset relationship.", "rowset relationship create \"{dataset_key}\" --source-column person_id --target-dataset-key \"{people_key}\""},
	"relationship resolve":    {"rowset relationship resolve DATASET_KEY RELATIONSHIP_KEY --source-index-value VALUE", "Resolve a relationship value.", "rowset relationship resolve \"{dataset_key}\" \"{relationship_key}\" --source-index-value P-1"},
	"relationship delete":     {"rowset relationship delete DATASET_KEY RELATIONSHIP_KEY", "Delete a relationship definition.", "rowset relationship delete \"{dataset_key}\" \"{relationship_key}\""},
	"row":                     {"rowset row <command>", "Search and manage dataset rows.", "rowset row get \"{dataset_key}\" 7"},
	"row list":                {"rowset row list DATASET_KEY [flags]", "List dataset rows.", "rowset row list \"{dataset_key}\" --limit 10"},
	"row search":              {"rowset row search QUERY [flags]", "Search rows across datasets.", "rowset row search \"renewal risks\" --limit 10"},
	"row search-dataset":      {"rowset row search-dataset DATASET_KEY QUERY [flags]", "Search rows within one dataset.", "rowset row search-dataset \"{dataset_key}\" \"stale tasks\" --limit 3"},
	"row get":                 {"rowset row get DATASET_KEY ROW_ID", "Get a row by internal ID.", "rowset row get \"{dataset_key}\" 7"},
	"row get-by-index":        {"rowset row get-by-index DATASET_KEY INDEX_VALUE", "Get a row by stable index.", "rowset row get-by-index \"{dataset_key}\" T-1"},
	"row create":              {"rowset row create DATASET_KEY --data JSON", "Create a row.", "rowset row create \"{dataset_key}\" --data '{\"task_id\":\"T-1\"}'"},
	"row update":              {"rowset row update DATASET_KEY ROW_ID --data JSON", "Update a row by internal ID.", "rowset row update \"{dataset_key}\" 7 --data '{\"status\":\"Done\"}'"},
	"row update-by-index":     {"rowset row update-by-index DATASET_KEY INDEX_VALUE --data JSON", "Update a row by stable index.", "rowset row update-by-index \"{dataset_key}\" T-1 --data '{\"status\":\"Done\"}'"},
	"row delete":              {"rowset row delete DATASET_KEY ROW_ID", "Delete a row.", "rowset row delete \"{dataset_key}\" 7"},
	"asset":                   {"rowset asset <command>", "Attach and retrieve row assets.", "rowset asset get \"{dataset_key}\" \"{asset_key}\""},
	"asset attach":            {"rowset asset attach DATASET_KEY --column COLUMN --file PATH (--row-id ID | --index-value VALUE) [flags]", "Attach an image or audio file.", "rowset asset attach \"{dataset_key}\" --index-value T-1 --column photo --file ./photo.png"},
	"asset get":               {"rowset asset get DATASET_KEY ASSET_KEY", "Inspect asset metadata.", "rowset asset get \"{dataset_key}\" \"{asset_key}\""},
	"asset content":           {"rowset asset content DATASET_KEY ASSET_KEY [--variant original|thumbnail] [--output PATH]", "Download asset bytes.", "rowset asset content \"{dataset_key}\" \"{asset_key}\" --output asset.bin"},
	"export":                  {"rowset export DATASET_KEY csv|jsonl|xlsx|sqlite [--output PATH]", "Export a dataset snapshot.", "rowset export \"{dataset_key}\" csv --output dataset.csv"},
	"request":                 {"rowset request METHOD PATH [--json JSON | --file PATH] [--output PATH] [--no-auth]", "Call a REST path directly.", "rowset request GET /datasets/\"{dataset_key}\""},
}

func requestedHelp(args []string) ([]string, bool) {
	path := commandPath(args)
	if len(path) < len(args) && (args[len(path)] == "--help" || args[len(path)] == "-h") {
		return path, true
	}
	return nil, false
}

func commandPath(args []string) []string {
	path := make([]string, 0, 3)
	for index, arg := range args {
		if strings.HasPrefix(arg, "-") {
			continue
		}
		if index == 0 && arg == "apikey" {
			arg = "api-key"
		}
		candidate := strings.Join(append(path, arg), " ")
		if _, ok := commandHelp[candidate]; !ok {
			break
		}
		path = append(path, arg)
	}
	return path
}

func printCommandHelp(w io.Writer, args []string) error {
	if len(args) == 0 {
		printHelp(w)
		return nil
	}
	path := commandPath(args)
	key := strings.Join(path, " ")
	entry, ok := commandHelp[key]
	if !ok || len(path) != len(args) {
		return fmt.Errorf("unknown help topic %q", strings.Join(args, " "))
	}
	_, _ = fmt.Fprintf(w, "%s\n\nUsage: %s\n", entry.summary, entry.usage)
	children := directHelpChildren(key)
	if len(children) > 0 {
		_, _ = fmt.Fprintln(w, "\nCommands:")
		for _, child := range children {
			childEntry := commandHelp[key+" "+child]
			_, _ = fmt.Fprintf(w, "  %-16s %s\n", child, childEntry.summary)
		}
	}
	_, _ = fmt.Fprintf(w, "\nExample:\n  %s\n", entry.example)
	return nil
}

func directHelpChildren(key string) []string {
	prefix := ""
	if key != "" {
		prefix = key + " "
	}
	children := []string{}
	for candidate := range commandHelp {
		remainder, ok := strings.CutPrefix(candidate, prefix)
		if !ok {
			continue
		}
		if !strings.Contains(remainder, " ") {
			children = append(children, remainder)
		}
	}
	sort.Strings(children)
	return children
}

func printHelp(w io.Writer) {
	_, _ = fmt.Fprint(w, `rowset is the Rowset REST CLI.

Configuration:
  ROWSET_API_BASE   Rowset REST API base (default https://rowset.lvtd.dev/api/)
  ROWSET_API_KEY    Rowset API key sent as Authorization: Bearer <key>

Global flags:
  --api-base URL       override ROWSET_API_BASE
  --api-key-env NAME   env var containing the API key (default ROWSET_API_KEY)
  --compact            write JSON responses on one line
  --help               show root help (use COMMAND --help for nested help)
  --version            show the CLI version

Commands:
`)
	for _, command := range directHelpChildren("") {
		entry := commandHelp[command]
		_, _ = fmt.Fprintf(w, "  %-54s %s\n", strings.TrimPrefix(entry.usage, "rowset "), entry.summary)
	}
}
