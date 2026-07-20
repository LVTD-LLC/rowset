package rowsetcli

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

const defaultAPIBase = "https://rowset.lvtd.dev/api/"

var Version = "dev"

type IO struct {
	Stdin  io.Reader
	Stdout io.Writer
	Stderr io.Writer
}

type config struct {
	apiBase   string
	apiKeyEnv string
	compact   bool
}

type requestOptions struct {
	auth       bool
	body       any
	bodyBytes  []byte
	outputPath string
	rawOutput  bool
}

type repeatedStrings []string

type apiErrorResponse struct {
	Code       string `json:"code"`
	Message    string `json:"message"`
	Detail     string `json:"detail"`
	UpgradeURL string `json:"upgrade_url"`
}

func (values *repeatedStrings) String() string {
	return strings.Join(*values, ",")
}

func (values *repeatedStrings) Set(value string) error {
	*values = append(*values, value)
	return nil
}

func Run(ctx context.Context, streams IO, args []string) error {
	if streams.Stdin == nil {
		streams.Stdin = os.Stdin
	}
	if streams.Stdout == nil {
		streams.Stdout = os.Stdout
	}
	if streams.Stderr == nil {
		streams.Stderr = os.Stderr
	}

	cfg := config{
		apiBase:   envOrDefault("ROWSET_API_BASE", defaultAPIBase),
		apiKeyEnv: "ROWSET_API_KEY",
	}

	global := flag.NewFlagSet("rowset", flag.ContinueOnError)
	global.SetOutput(io.Discard)
	global.StringVar(&cfg.apiBase, "api-base", cfg.apiBase, "Rowset REST API base URL")
	global.StringVar(&cfg.apiKeyEnv, "api-key-env", cfg.apiKeyEnv, "environment variable containing the Rowset API key")
	global.BoolVar(&cfg.compact, "compact", false, "write JSON responses on one line")
	showHelp := global.Bool("help", false, "show help")
	showVersion := global.Bool("version", false, "show version")
	if err := global.Parse(args); err != nil {
		return err
	}
	if *showVersion {
		_, _ = fmt.Fprintf(streams.Stdout, "rowset %s\n", Version)
		return nil
	}
	if *showHelp || len(global.Args()) == 0 {
		printHelp(streams.Stdout)
		return nil
	}
	if helpArgs, ok := requestedHelp(global.Args()); ok {
		return printCommandHelp(streams.Stdout, helpArgs)
	}

	return dispatch(ctx, streams, cfg, global.Args())
}

func dispatch(ctx context.Context, streams IO, cfg config, args []string) error {
	switch args[0] {
	case "capabilities":
		return runCapabilities(ctx, streams, cfg, args[1:])
	case "healthcheck":
		return doRequest(ctx, streams, cfg, http.MethodGet, "/healthcheck", nil, requestOptions{})
	case "user":
		return runUser(ctx, streams, cfg, args[1:])
	case "feedback":
		return runFeedback(ctx, streams, cfg, args[1:])
	case "api-key", "apikey":
		return runAPIKey(ctx, streams, cfg, args[1:])
	case "project":
		return runProject(ctx, streams, cfg, args[1:])
	case "dataset":
		return runDataset(ctx, streams, cfg, args[1:])
	case "preview":
		return runPreview(ctx, streams, cfg, args[1:])
	case "column":
		return runColumn(ctx, streams, cfg, args[1:])
	case "relationship":
		return runRelationship(ctx, streams, cfg, args[1:])
	case "row":
		return runRow(ctx, streams, cfg, args[1:])
	case "asset":
		return runAsset(ctx, streams, cfg, args[1:])
	case "export":
		return runExport(ctx, streams, cfg, args[1:])
	case "request":
		return runRawRequest(ctx, streams, cfg, args[1:])
	case "help":
		return printCommandHelp(streams.Stdout, args[1:])
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func runCapabilities(ctx context.Context, streams IO, cfg config, args []string) error {
	fs := newFlagSet("capabilities")
	var topicValues repeatedStrings
	fs.Var(&topicValues, "topic", "capability topic (repeatable or comma-separated)")
	includeUseCases := fs.Bool("include-use-cases", false, "include relevant use cases")
	full := fs.Bool("full", false, "return the complete capability guide")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if len(topicValues) > 0 && *full {
		return errors.New("--topic cannot be combined with --full")
	}

	topics := make([]string, 0, len(topicValues))
	for _, value := range topicValues {
		topics = append(topics, splitCSV(value)...)
	}
	values := url.Values{}
	addQuery(values, "topics", strings.Join(topics, ","))
	if *includeUseCases {
		values.Set("include_use_cases", "true")
	}
	if *full {
		values.Set("full", "true")
	}
	return doRequest(ctx, streams, cfg, http.MethodGet, "/capabilities", values, requestOptions{})
}

func runUser(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 || args[0] != "info" {
		return errors.New("usage: rowset user info")
	}
	return doRequest(ctx, streams, cfg, http.MethodGet, "/user", nil, requestOptions{auth: true})
}

func runFeedback(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 || args[0] != "submit" {
		return errors.New("usage: rowset feedback submit --feedback TEXT [--page PATH] [--context JSON]")
	}
	fs := newFlagSet("feedback submit")
	feedback := fs.String("feedback", "", "feedback text")
	page := fs.String("page", "", "page or context path")
	contextJSON := fs.String("context", "", "JSON object with feedback context")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if *feedback == "" {
		return errors.New("--feedback is required")
	}
	body := map[string]any{"feedback": *feedback}
	if flagWasSet(fs, "page") {
		body["page"] = *page
	}
	if flagWasSet(fs, "context") {
		context, err := parseJSONObject(*contextJSON, "--context")
		if err != nil {
			return err
		}
		body["context"] = context
	}
	return doRequest(ctx, streams, cfg, http.MethodPost, "/feedback", nil, requestOptions{
		auth: true,
		body: body,
	})
}

func runAPIKey(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 || args[0] != "create" {
		return errors.New("usage: rowset api-key create --name NAME [--access-level read|read_write|admin]")
	}
	fs := newFlagSet("api-key create")
	name := fs.String("name", "", "API key name")
	accessLevel := fs.String("access-level", "read_write", "access level")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if *name == "" {
		return errors.New("--name is required")
	}
	return doRequest(ctx, streams, cfg, http.MethodPost, "/agent-api-keys", nil, requestOptions{
		auth: true,
		body: map[string]any{"name": *name, "access_level": *accessLevel},
	})
}

func runProject(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 {
		return errors.New("usage: rowset project <list|search|create|get|update|metadata|archive|section>")
	}
	switch args[0] {
	case "list":
		fs := newFlagSet("project list")
		limit, offset := paginationFlags(fs, 100, 0)
		query := fs.String("query", "", "project search query")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		values := paginationValues(*limit, *offset)
		addQuery(values, "query", *query)
		return doRequest(ctx, streams, cfg, http.MethodGet, "/projects", values, requestOptions{auth: true})
	case "search":
		if len(args) < 2 {
			return errors.New("usage: rowset project search QUERY [--limit N] [--offset N]")
		}
		fs := newFlagSet("project search")
		limit, offset := paginationFlags(fs, 100, 0)
		if err := fs.Parse(args[2:]); err != nil {
			return err
		}
		values := paginationValues(*limit, *offset)
		values.Set("query", args[1])
		return doRequest(ctx, streams, cfg, http.MethodGet, "/projects", values, requestOptions{auth: true})
	case "create":
		return createProject(ctx, streams, cfg, args[1:])
	case "get":
		if len(args) < 2 {
			return errors.New("usage: rowset project get PROJECT_KEY [--limit N] [--offset N]")
		}
		fs := newFlagSet("project get")
		limit, offset := paginationFlags(fs, 100, 0)
		if err := fs.Parse(args[2:]); err != nil {
			return err
		}
		return doRequest(
			ctx,
			streams,
			cfg,
			http.MethodGet,
			apiPath("projects", args[1]),
			paginationValues(*limit, *offset),
			requestOptions{auth: true},
		)
	case "update":
		return updateProject(ctx, streams, cfg, args[1:])
	case "metadata":
		return updateProjectMetadata(ctx, streams, cfg, args[1:])
	case "archive":
		if len(args) != 2 {
			return errors.New("usage: rowset project archive PROJECT_KEY")
		}
		return doRequest(ctx, streams, cfg, http.MethodDelete, apiPath("projects", args[1]), nil, requestOptions{auth: true})
	case "section":
		return runProjectSection(ctx, streams, cfg, args[1:])
	default:
		return fmt.Errorf("unknown project command %q", args[0])
	}
}

func createProject(ctx context.Context, streams IO, cfg config, args []string) error {
	fs := newFlagSet("project create")
	name := fs.String("name", "", "project name")
	description := fs.String("description", "", "project description")
	metadataJSON := fs.String("metadata", "", "project metadata JSON object")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *name == "" {
		return errors.New("--name is required")
	}
	body := map[string]any{"name": *name}
	if flagWasSet(fs, "description") {
		body["description"] = *description
	}
	if flagWasSet(fs, "metadata") {
		metadata, err := parseJSONObject(*metadataJSON, "--metadata")
		if err != nil {
			return err
		}
		body["metadata"] = metadata
	}
	return doRequest(ctx, streams, cfg, http.MethodPost, "/projects", nil, requestOptions{auth: true, body: body})
}

func updateProject(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset project update PROJECT_KEY [--name NAME] [--description TEXT]")
	}
	fs := newFlagSet("project update")
	name := fs.String("name", "", "project name")
	description := fs.String("description", "", "project description")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	body := map[string]any{}
	if flagWasSet(fs, "name") {
		body["name"] = *name
	}
	if flagWasSet(fs, "description") {
		body["description"] = *description
	}
	if len(body) == 0 {
		return errors.New("at least one of --name or --description is required")
	}
	return doRequest(ctx, streams, cfg, http.MethodPatch, apiPath("projects", args[0]), nil, requestOptions{auth: true, body: body})
}

func updateProjectMetadata(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset project metadata PROJECT_KEY --metadata JSON")
	}
	fs := newFlagSet("project metadata")
	metadataJSON := fs.String("metadata", "", "project metadata JSON object")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if !flagWasSet(fs, "metadata") {
		return errors.New("--metadata is required")
	}
	metadata, err := parseJSONObject(*metadataJSON, "--metadata")
	if err != nil {
		return err
	}
	return doRequest(ctx, streams, cfg, http.MethodPatch, apiPath("projects", args[0], "metadata"), nil, requestOptions{
		auth: true,
		body: map[string]any{"metadata": metadata},
	})
}

func runProjectSection(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 {
		return errors.New("usage: rowset project section <list|create|update|archive>")
	}
	switch args[0] {
	case "list":
		if len(args) < 2 {
			return errors.New("usage: rowset project section list PROJECT_KEY [--limit N] [--offset N]")
		}
		fs := newFlagSet("project section list")
		limit, offset := paginationFlags(fs, 100, 0)
		if err := fs.Parse(args[2:]); err != nil {
			return err
		}
		return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("projects", args[1], "sections"), paginationValues(*limit, *offset), requestOptions{auth: true})
	case "create":
		if len(args) < 2 {
			return errors.New("usage: rowset project section create PROJECT_KEY --name NAME")
		}
		return createProjectSection(ctx, streams, cfg, args[1], args[2:])
	case "update":
		if len(args) < 3 {
			return errors.New("usage: rowset project section update PROJECT_KEY SECTION_KEY [--name NAME] [--description TEXT]")
		}
		return updateProjectSection(ctx, streams, cfg, args[1], args[2], args[3:])
	case "archive":
		if len(args) != 3 {
			return errors.New("usage: rowset project section archive PROJECT_KEY SECTION_KEY")
		}
		return doRequest(ctx, streams, cfg, http.MethodDelete, apiPath("projects", args[1], "sections", args[2]), nil, requestOptions{auth: true})
	default:
		return fmt.Errorf("unknown project section command %q", args[0])
	}
}

func createProjectSection(ctx context.Context, streams IO, cfg config, projectKey string, args []string) error {
	fs := newFlagSet("project section create")
	name := fs.String("name", "", "section name")
	description := fs.String("description", "", "section description")
	metadataJSON := fs.String("metadata", "", "section metadata JSON object")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *name == "" {
		return errors.New("--name is required")
	}
	body := map[string]any{"name": *name}
	if flagWasSet(fs, "description") {
		body["description"] = *description
	}
	if flagWasSet(fs, "metadata") {
		metadata, err := parseJSONObject(*metadataJSON, "--metadata")
		if err != nil {
			return err
		}
		body["metadata"] = metadata
	}
	return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("projects", projectKey, "sections"), nil, requestOptions{auth: true, body: body})
}

func updateProjectSection(ctx context.Context, streams IO, cfg config, projectKey string, sectionKey string, args []string) error {
	fs := newFlagSet("project section update")
	name := fs.String("name", "", "section name")
	description := fs.String("description", "", "section description")
	if err := fs.Parse(args); err != nil {
		return err
	}
	body := map[string]any{}
	if flagWasSet(fs, "name") {
		body["name"] = *name
	}
	if flagWasSet(fs, "description") {
		body["description"] = *description
	}
	if len(body) == 0 {
		return errors.New("at least one of --name or --description is required")
	}
	return doRequest(ctx, streams, cfg, http.MethodPatch, apiPath("projects", projectKey, "sections", sectionKey), nil, requestOptions{auth: true, body: body})
}

func runDataset(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 {
		return errors.New("usage: rowset dataset <list|search|archived|get|create|metadata|column-types|project|archive|restore>")
	}
	switch args[0] {
	case "list":
		return listDatasets(ctx, streams, cfg, args[1:])
	case "search":
		if len(args) < 2 {
			return errors.New("usage: rowset dataset search QUERY [filters]")
		}
		return listDatasets(ctx, streams, cfg, append([]string{"--query", args[1]}, args[2:]...))
	case "archived":
		fs := newFlagSet("dataset archived")
		limit, offset := paginationFlags(fs, 100, 0)
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		return doRequest(ctx, streams, cfg, http.MethodGet, "/datasets/archived", paginationValues(*limit, *offset), requestOptions{auth: true})
	case "get":
		if len(args) != 2 {
			return errors.New("usage: rowset dataset get DATASET_KEY")
		}
		return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("datasets", args[1]), nil, requestOptions{auth: true})
	case "create":
		return createDataset(ctx, streams, cfg, args[1:])
	case "metadata":
		return updateDatasetMetadata(ctx, streams, cfg, args[1:])
	case "column-types":
		return updateDatasetColumnTypes(ctx, streams, cfg, args[1:])
	case "project":
		return updateDatasetProject(ctx, streams, cfg, args[1:])
	case "archive":
		if len(args) != 2 {
			return errors.New("usage: rowset dataset archive DATASET_KEY")
		}
		return doRequest(ctx, streams, cfg, http.MethodDelete, apiPath("datasets", args[1]), nil, requestOptions{auth: true})
	case "restore":
		if len(args) != 2 {
			return errors.New("usage: rowset dataset restore DATASET_KEY")
		}
		return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[1], "restore"), nil, requestOptions{auth: true})
	default:
		return fmt.Errorf("unknown dataset command %q", args[0])
	}
}

func listDatasets(ctx context.Context, streams IO, cfg config, args []string) error {
	fs := newFlagSet("dataset list")
	limit, offset := paginationFlags(fs, 100, 0)
	query := fs.String("query", "", "dataset search query")
	projectKey := fs.String("project-key", "", "project key")
	sectionKey := fs.String("section-key", "", "project section key")
	headerContains := fs.String("header-contains", "", "exact header name")
	status := fs.String("status", "", "dataset status")
	updatedAfter := fs.String("updated-after", "", "ISO date or datetime")
	if err := fs.Parse(args); err != nil {
		return err
	}
	values := paginationValues(*limit, *offset)
	addQuery(values, "query", *query)
	addQuery(values, "project_key", *projectKey)
	addQuery(values, "section_key", *sectionKey)
	addQuery(values, "header_contains", *headerContains)
	addQuery(values, "status", *status)
	addQuery(values, "updated_after", *updatedAfter)
	return doRequest(ctx, streams, cfg, http.MethodGet, "/datasets", values, requestOptions{auth: true})
}

func createDataset(ctx context.Context, streams IO, cfg config, args []string) error {
	fs := newFlagSet("dataset create")
	name := fs.String("name", "", "dataset name")
	description := fs.String("description", "", "dataset description")
	instructions := fs.String("instructions", "", "persistent agent instructions")
	metadataJSON := fs.String("metadata", "", "dataset metadata JSON object")
	headers := fs.String("headers", "", "comma-separated headers")
	indexColumn := fs.String("index-column", "", "index column")
	columnTypesJSON := fs.String("column-types", "", "column type JSON object")
	projectKey := fs.String("project-key", "", "project key")
	sectionKey := fs.String("section-key", "", "section key")
	rowsJSON := fs.String("rows", "", "JSON array of rows")
	var rowValues repeatedStrings
	fs.Var(&rowValues, "row", "JSON object row; may be repeated")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *name == "" {
		return errors.New("--name is required")
	}
	body := map[string]any{"name": *name}
	if flagWasSet(fs, "description") {
		body["description"] = *description
	}
	if flagWasSet(fs, "instructions") {
		body["instructions"] = *instructions
	}
	if flagWasSet(fs, "metadata") {
		metadata, err := parseJSONObject(*metadataJSON, "--metadata")
		if err != nil {
			return err
		}
		body["metadata"] = metadata
	}
	if flagWasSet(fs, "headers") {
		body["headers"] = splitCSV(*headers)
	}
	if flagWasSet(fs, "index-column") {
		body["index_column"] = *indexColumn
	}
	if flagWasSet(fs, "column-types") {
		columnTypes, err := parseJSONObject(*columnTypesJSON, "--column-types")
		if err != nil {
			return err
		}
		body["column_types"] = columnTypes
	}
	if flagWasSet(fs, "project-key") {
		body["project_key"] = *projectKey
	}
	if flagWasSet(fs, "section-key") {
		body["section_key"] = *sectionKey
	}
	rows, err := parseRows(*rowsJSON, rowValues)
	if err != nil {
		return err
	}
	if rows != nil {
		body["rows"] = rows
	}
	return doRequest(ctx, streams, cfg, http.MethodPost, "/datasets", nil, requestOptions{auth: true, body: body})
}

func updateDatasetMetadata(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset dataset metadata DATASET_KEY [--description TEXT] [--instructions TEXT] [--metadata JSON]")
	}
	fs := newFlagSet("dataset metadata")
	description := fs.String("description", "", "dataset description")
	instructions := fs.String("instructions", "", "dataset instructions")
	metadataJSON := fs.String("metadata", "", "dataset metadata JSON object")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	body := map[string]any{}
	if flagWasSet(fs, "description") {
		body["description"] = *description
	}
	if flagWasSet(fs, "instructions") {
		body["instructions"] = *instructions
	}
	if flagWasSet(fs, "metadata") {
		metadata, err := parseJSONObject(*metadataJSON, "--metadata")
		if err != nil {
			return err
		}
		body["metadata"] = metadata
	}
	if len(body) == 0 {
		return errors.New("at least one metadata field is required")
	}
	return doRequest(ctx, streams, cfg, http.MethodPatch, apiPath("datasets", args[0], "metadata"), nil, requestOptions{auth: true, body: body})
}

func updateDatasetColumnTypes(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset dataset column-types DATASET_KEY --column-types JSON")
	}
	fs := newFlagSet("dataset column-types")
	columnTypesJSON := fs.String("column-types", "", "column type JSON object")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if !flagWasSet(fs, "column-types") {
		return errors.New("--column-types is required")
	}
	columnTypes, err := parseJSONObject(*columnTypesJSON, "--column-types")
	if err != nil {
		return err
	}
	return doRequest(ctx, streams, cfg, http.MethodPatch, apiPath("datasets", args[0], "column-types"), nil, requestOptions{
		auth: true,
		body: map[string]any{"column_types": columnTypes},
	})
}

func updateDatasetProject(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset dataset project DATASET_KEY (--project-key KEY [--section-key KEY] | --clear)")
	}
	fs := newFlagSet("dataset project")
	projectKey := fs.String("project-key", "", "project key")
	sectionKey := fs.String("section-key", "", "section key")
	clearProject := fs.Bool("clear", false, "remove project assignment")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	body := map[string]any{}
	if *clearProject {
		body["project_key"] = nil
	} else if flagWasSet(fs, "project-key") {
		body["project_key"] = *projectKey
	} else {
		return errors.New("--project-key or --clear is required")
	}
	if flagWasSet(fs, "section-key") {
		body["section_key"] = *sectionKey
	}
	return doRequest(ctx, streams, cfg, http.MethodPatch, apiPath("datasets", args[0], "project"), nil, requestOptions{auth: true, body: body})
}

func runPreview(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 || args[0] != "update" || len(args) < 2 {
		return errors.New("usage: rowset preview update DATASET_KEY [--enabled true|false] [--page-size N] [--password TEXT] [--clear-password]")
	}
	fs := newFlagSet("preview update")
	enabled := fs.String("enabled", "", "true or false")
	pageSize := fs.Int("page-size", 0, "public preview page size")
	password := fs.String("password", "", "public preview password")
	clearPassword := fs.Bool("clear-password", false, "clear public preview password")
	if err := fs.Parse(args[2:]); err != nil {
		return err
	}
	body := map[string]any{}
	if flagWasSet(fs, "enabled") {
		value, err := strconv.ParseBool(*enabled)
		if err != nil {
			return fmt.Errorf("--enabled must be true or false: %w", err)
		}
		body["public_enabled"] = value
	}
	if flagWasSet(fs, "page-size") {
		body["public_page_size"] = *pageSize
	}
	if flagWasSet(fs, "password") {
		body["public_password"] = *password
	}
	if *clearPassword {
		body["clear_public_password"] = true
	}
	if len(body) == 0 {
		return errors.New("at least one preview setting is required")
	}
	return doRequest(ctx, streams, cfg, http.MethodPatch, apiPath("datasets", args[1], "public-preview"), nil, requestOptions{auth: true, body: body})
}

func runColumn(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 {
		return errors.New("usage: rowset column <add|rename|drop|reorder>")
	}
	switch args[0] {
	case "add":
		return addColumn(ctx, streams, cfg, args[1:])
	case "rename":
		if len(args) != 4 {
			return errors.New("usage: rowset column rename DATASET_KEY OLD_NAME NEW_NAME")
		}
		return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[1], "columns", "rename"), nil, requestOptions{
			auth: true,
			body: map[string]any{"old_name": args[2], "new_name": args[3]},
		})
	case "drop":
		if len(args) != 3 {
			return errors.New("usage: rowset column drop DATASET_KEY NAME")
		}
		return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[1], "columns", "drop"), nil, requestOptions{
			auth: true,
			body: map[string]any{"name": args[2]},
		})
	case "reorder":
		if len(args) < 2 {
			return errors.New("usage: rowset column reorder DATASET_KEY --headers a,b,c")
		}
		fs := newFlagSet("column reorder")
		headers := fs.String("headers", "", "comma-separated headers")
		if err := fs.Parse(args[2:]); err != nil {
			return err
		}
		if !flagWasSet(fs, "headers") {
			return errors.New("--headers is required")
		}
		return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[1], "columns", "reorder"), nil, requestOptions{
			auth: true,
			body: map[string]any{"headers": splitCSV(*headers)},
		})
	default:
		return fmt.Errorf("unknown column command %q", args[0])
	}
}

func addColumn(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset column add DATASET_KEY --name NAME")
	}
	fs := newFlagSet("column add")
	name := fs.String("name", "", "column name")
	defaultValue := fs.String("default-value", "", "default string value")
	defaultJSON := fs.String("default-json", "", "default JSON value")
	columnType := fs.String("column-type", "", "column type string or JSON object")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if *name == "" {
		return errors.New("--name is required")
	}
	body := map[string]any{"name": *name}
	if flagWasSet(fs, "default-json") {
		value, err := parseJSONValue(*defaultJSON, "--default-json")
		if err != nil {
			return err
		}
		body["default_value"] = value
	} else if flagWasSet(fs, "default-value") {
		body["default_value"] = *defaultValue
	}
	if flagWasSet(fs, "column-type") {
		value, err := parseMaybeJSON(*columnType, "--column-type")
		if err != nil {
			return err
		}
		body["column_type"] = value
	}
	return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[0], "columns"), nil, requestOptions{auth: true, body: body})
}

func runRelationship(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 {
		return errors.New("usage: rowset relationship <list|create|resolve|delete>")
	}
	switch args[0] {
	case "list":
		if len(args) != 2 {
			return errors.New("usage: rowset relationship list DATASET_KEY")
		}
		return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("datasets", args[1], "relationships"), nil, requestOptions{auth: true})
	case "create":
		return createRelationship(ctx, streams, cfg, args[1:])
	case "resolve":
		if len(args) < 3 {
			return errors.New("usage: rowset relationship resolve DATASET_KEY RELATIONSHIP_KEY --source-index-value VALUE")
		}
		fs := newFlagSet("relationship resolve")
		sourceIndexValue := fs.String("source-index-value", "", "source row index value")
		if err := fs.Parse(args[3:]); err != nil {
			return err
		}
		if *sourceIndexValue == "" {
			return errors.New("--source-index-value is required")
		}
		values := url.Values{}
		values.Set("source_index_value", *sourceIndexValue)
		return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("datasets", args[1], "relationships", args[2], "resolve"), values, requestOptions{auth: true})
	case "delete":
		if len(args) != 3 {
			return errors.New("usage: rowset relationship delete DATASET_KEY RELATIONSHIP_KEY")
		}
		return doRequest(ctx, streams, cfg, http.MethodDelete, apiPath("datasets", args[1], "relationships", args[2]), nil, requestOptions{auth: true})
	default:
		return fmt.Errorf("unknown relationship command %q", args[0])
	}
}

func createRelationship(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset relationship create DATASET_KEY --source-column COLUMN --target-dataset-key KEY")
	}
	fs := newFlagSet("relationship create")
	sourceColumn := fs.String("source-column", "", "source column")
	targetDatasetKey := fs.String("target-dataset-key", "", "target dataset key")
	name := fs.String("name", "", "relationship name")
	enforceIntegrity := fs.String("enforce-integrity", "true", "true or false")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if *sourceColumn == "" || *targetDatasetKey == "" {
		return errors.New("--source-column and --target-dataset-key are required")
	}
	enforce, err := strconv.ParseBool(*enforceIntegrity)
	if err != nil {
		return fmt.Errorf("--enforce-integrity must be true or false: %w", err)
	}
	body := map[string]any{
		"source_column":      *sourceColumn,
		"target_dataset_key": *targetDatasetKey,
		"enforce_integrity":  enforce,
	}
	if flagWasSet(fs, "name") {
		body["name"] = *name
	}
	return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[0], "relationships"), nil, requestOptions{auth: true, body: body})
}

func runRow(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 {
		return errors.New("usage: rowset row <list|search|search-dataset|get|get-by-index|create|update|update-by-index|delete>")
	}
	switch args[0] {
	case "list":
		return listRows(ctx, streams, cfg, args[1:])
	case "search":
		return searchRows(ctx, streams, cfg, args[1:])
	case "search-dataset":
		return searchDatasetRows(ctx, streams, cfg, args[1:])
	case "get":
		if len(args) != 3 {
			return errors.New("usage: rowset row get DATASET_KEY ROW_ID")
		}
		return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("datasets", args[1], "rows", args[2]), nil, requestOptions{auth: true})
	case "get-by-index":
		if len(args) != 3 {
			return errors.New("usage: rowset row get-by-index DATASET_KEY INDEX_VALUE")
		}
		values := url.Values{}
		values.Set("index_value", args[2])
		return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("datasets", args[1], "rows", "by-index"), values, requestOptions{auth: true})
	case "create":
		if len(args) < 2 {
			return errors.New("usage: rowset row create DATASET_KEY --data JSON")
		}
		return rowWrite(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[1], "rows"), nil, args[2:])
	case "update":
		if len(args) < 3 {
			return errors.New("usage: rowset row update DATASET_KEY ROW_ID --data JSON")
		}
		return rowWrite(ctx, streams, cfg, http.MethodPatch, apiPath("datasets", args[1], "rows", args[2]), nil, args[3:])
	case "update-by-index":
		if len(args) < 3 {
			return errors.New("usage: rowset row update-by-index DATASET_KEY INDEX_VALUE --data JSON")
		}
		values := url.Values{}
		values.Set("index_value", args[2])
		return rowWrite(ctx, streams, cfg, http.MethodPatch, apiPath("datasets", args[1], "rows", "by-index"), values, args[3:])
	case "delete":
		if len(args) != 3 {
			return errors.New("usage: rowset row delete DATASET_KEY ROW_ID")
		}
		return doRequest(ctx, streams, cfg, http.MethodDelete, apiPath("datasets", args[1], "rows", args[2]), nil, requestOptions{auth: true})
	default:
		return fmt.Errorf("unknown row command %q", args[0])
	}
}

func listRows(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset row list DATASET_KEY [--limit N] [--filters JSON]")
	}
	fs := newFlagSet("row list")
	limit, offset := paginationFlags(fs, 100, 0)
	query := fs.String("query", "", "row query")
	filters := fs.String("filters", "", "row filters JSON object")
	sort := fs.String("sort", "", "sort header")
	direction := fs.String("direction", "", "asc or desc")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	values := paginationValues(*limit, *offset)
	addQuery(values, "query", *query)
	addQuery(values, "filters", *filters)
	addQuery(values, "sort", *sort)
	addQuery(values, "direction", *direction)
	return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("datasets", args[0], "rows"), values, requestOptions{auth: true})
}

func searchRows(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset row search QUERY [filters]")
	}
	fs := newFlagSet("row search")
	filtersJSON := fs.String("filters", "", "row filters JSON object")
	filterOperatorsJSON := fs.String("filter-operators", "", "filter operators JSON object")
	datasetKey := fs.String("dataset-key", "", "dataset key")
	projectKey := fs.String("project-key", "", "project key")
	sectionKey := fs.String("section-key", "", "section key")
	status := fs.String("status", "", "dataset status")
	archived := fs.String("archived", "", "true, false, or null")
	sort := fs.String("sort", "", "rank, dataset, or row_number")
	direction := fs.String("direction", "", "asc or desc")
	limit := fs.Int("limit", 10, "result limit")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	body := map[string]any{"query": args[0]}
	if flagWasSet(fs, "filters") {
		value, err := parseJSONObject(*filtersJSON, "--filters")
		if err != nil {
			return err
		}
		body["filters"] = value
	}
	if flagWasSet(fs, "filter-operators") {
		value, err := parseJSONObject(*filterOperatorsJSON, "--filter-operators")
		if err != nil {
			return err
		}
		body["filter_operators"] = value
	}
	if flagWasSet(fs, "dataset-key") {
		body["dataset_key"] = *datasetKey
	}
	if flagWasSet(fs, "project-key") {
		body["project_key"] = *projectKey
	}
	if flagWasSet(fs, "section-key") {
		body["section_key"] = *sectionKey
	}
	if flagWasSet(fs, "status") {
		body["status"] = *status
	}
	if flagWasSet(fs, "archived") {
		if strings.EqualFold(*archived, "null") {
			body["archived"] = nil
		} else {
			value, err := strconv.ParseBool(*archived)
			if err != nil {
				return fmt.Errorf("--archived must be true, false, or null: %w", err)
			}
			body["archived"] = value
		}
	}
	if flagWasSet(fs, "sort") {
		body["sort"] = *sort
	}
	if flagWasSet(fs, "direction") {
		body["direction"] = *direction
	}
	if flagWasSet(fs, "limit") {
		body["limit"] = *limit
	}
	return doRequest(ctx, streams, cfg, http.MethodPost, "/search", nil, requestOptions{auth: true, body: body})
}

func searchDatasetRows(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 2 {
		return errors.New("usage: rowset row search-dataset DATASET_KEY QUERY [--filters JSON] [--limit N]")
	}
	fs := newFlagSet("row search-dataset")
	filtersJSON := fs.String("filters", "", "row filters JSON object")
	limit := fs.Int("limit", 10, "result limit")
	if err := fs.Parse(args[2:]); err != nil {
		return err
	}
	body := map[string]any{"query": args[1]}
	if flagWasSet(fs, "filters") {
		value, err := parseJSONObject(*filtersJSON, "--filters")
		if err != nil {
			return err
		}
		body["filters"] = value
	}
	if flagWasSet(fs, "limit") {
		body["limit"] = *limit
	}
	return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[0], "search"), nil, requestOptions{auth: true, body: body})
}

func rowWrite(ctx context.Context, streams IO, cfg config, method string, path string, query url.Values, args []string) error {
	fs := newFlagSet("row write")
	dataJSON := fs.String("data", "", "row data JSON object")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if !flagWasSet(fs, "data") {
		return errors.New("--data is required")
	}
	data, err := parseJSONObject(*dataJSON, "--data")
	if err != nil {
		return err
	}
	return doRequest(ctx, streams, cfg, method, path, query, requestOptions{
		auth: true,
		body: map[string]any{"data": data},
	})
}

func runAsset(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) == 0 {
		return errors.New("usage: rowset asset <attach|get|content>")
	}
	switch args[0] {
	case "attach":
		return attachAsset(ctx, streams, cfg, args[1:])
	case "get":
		if len(args) != 3 {
			return errors.New("usage: rowset asset get DATASET_KEY ASSET_KEY")
		}
		return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("datasets", args[1], "assets", args[2]), nil, requestOptions{auth: true})
	case "content":
		if len(args) < 3 {
			return errors.New("usage: rowset asset content DATASET_KEY ASSET_KEY [--variant original|thumbnail] [--output PATH]")
		}
		fs := newFlagSet("asset content")
		variant := fs.String("variant", "original", "asset variant")
		output := fs.String("output", "", "output path")
		if err := fs.Parse(args[3:]); err != nil {
			return err
		}
		values := url.Values{}
		values.Set("variant", *variant)
		return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("datasets", args[1], "assets", args[2], "content"), values, requestOptions{
			auth:       true,
			outputPath: *output,
			rawOutput:  true,
		})
	default:
		return fmt.Errorf("unknown asset command %q", args[0])
	}
}

func attachAsset(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 1 {
		return errors.New("usage: rowset asset attach DATASET_KEY --column COLUMN --file PATH (--row-id ID | --index-value VALUE) [--asset-type image|audio]")
	}
	fs := newFlagSet("asset attach")
	rowID := fs.String("row-id", "", "row id")
	indexValue := fs.String("index-value", "", "row index value")
	assetType := fs.String("asset-type", "image", "asset type: image or audio")
	column := fs.String("column", "", "asset column")
	filePath := fs.String("file", "", "asset file path")
	filename := fs.String("filename", "", "original filename")
	contentType := fs.String("content-type", "", "asset content type")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	if *column == "" || *filePath == "" {
		return errors.New("--column and --file are required")
	}
	if (*rowID == "" && *indexValue == "") || (*rowID != "" && *indexValue != "") {
		return errors.New("pass exactly one of --row-id or --index-value")
	}
	normalizedAssetType := strings.ToLower(strings.TrimSpace(*assetType))
	if normalizedAssetType != "image" && normalizedAssetType != "audio" {
		return errors.New("--asset-type must be image or audio")
	}
	data, err := os.ReadFile(*filePath)
	if err != nil {
		return fmt.Errorf("read asset file: %w", err)
	}
	base64Field := normalizedAssetType + "_base64"
	body := map[string]any{
		"column_name": *column,
		base64Field:   base64.StdEncoding.EncodeToString(data),
	}
	if flagWasSet(fs, "filename") {
		body["filename"] = *filename
	} else {
		body["filename"] = filepath.Base(*filePath)
	}
	if flagWasSet(fs, "content-type") {
		body["content_type"] = *contentType
	}
	if *rowID != "" {
		return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[0], "rows", *rowID, normalizedAssetType), nil, requestOptions{auth: true, body: body})
	}
	values := url.Values{}
	values.Set("index_value", *indexValue)
	return doRequest(ctx, streams, cfg, http.MethodPost, apiPath("datasets", args[0], "rows", "by-index", normalizedAssetType), values, requestOptions{auth: true, body: body})
}

func runExport(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 2 {
		return errors.New("usage: rowset export DATASET_KEY csv|jsonl|xlsx|sqlite [--output PATH]")
	}
	format := strings.TrimPrefix(strings.ToLower(args[1]), ".")
	switch format {
	case "csv", "jsonl", "xlsx", "sqlite":
	default:
		return fmt.Errorf("unsupported export format %q", args[1])
	}
	fs := newFlagSet("export")
	output := fs.String("output", "", "output path")
	if err := fs.Parse(args[2:]); err != nil {
		return err
	}
	return doRequest(ctx, streams, cfg, http.MethodGet, apiPath("datasets", args[0], "export."+format), nil, requestOptions{
		auth:       true,
		outputPath: *output,
		rawOutput:  true,
	})
}

func runRawRequest(ctx context.Context, streams IO, cfg config, args []string) error {
	if len(args) < 2 {
		return errors.New("usage: rowset request METHOD PATH [--json JSON | --file PATH] [--output PATH] [--no-auth]")
	}
	method := strings.ToUpper(args[0])
	path := args[1]
	fs := newFlagSet("request")
	jsonBody := fs.String("json", "", "JSON request body")
	bodyFile := fs.String("file", "", "file containing request body")
	output := fs.String("output", "", "output path")
	noAuth := fs.Bool("no-auth", false, "do not send bearer auth")
	if err := fs.Parse(args[2:]); err != nil {
		return err
	}
	var bodyBytes []byte
	if flagWasSet(fs, "json") && flagWasSet(fs, "file") {
		return errors.New("use only one of --json or --file")
	}
	if flagWasSet(fs, "json") {
		if !json.Valid([]byte(*jsonBody)) {
			return errors.New("--json must be valid JSON")
		}
		bodyBytes = []byte(*jsonBody)
	}
	if flagWasSet(fs, "file") {
		data, err := os.ReadFile(*bodyFile)
		if err != nil {
			return fmt.Errorf("read request file: %w", err)
		}
		bodyBytes = data
	}
	return doRequest(ctx, streams, cfg, method, path, nil, requestOptions{
		auth:       !*noAuth,
		bodyBytes:  bodyBytes,
		outputPath: *output,
		rawOutput:  *output != "",
	})
}

func doRequest(
	ctx context.Context,
	streams IO,
	cfg config,
	method string,
	path string,
	query url.Values,
	opts requestOptions,
) error {
	endpoint, err := buildEndpoint(cfg.apiBase, path, query, !opts.auth)
	if err != nil {
		return err
	}

	var body io.Reader
	if opts.body != nil {
		data, err := json.Marshal(opts.body)
		if err != nil {
			return fmt.Errorf("encode request body: %w", err)
		}
		body = bytes.NewReader(data)
	} else if opts.bodyBytes != nil {
		body = bytes.NewReader(opts.bodyBytes)
	}

	req, err := http.NewRequestWithContext(ctx, method, endpoint, body)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "rowset/"+Version)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if opts.auth {
		apiKey := os.Getenv(cfg.apiKeyEnv)
		if strings.TrimSpace(apiKey) == "" {
			return fmt.Errorf("%s is required for authenticated Rowset requests", cfg.apiKeyEnv)
		}
		req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(apiKey))
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	responseBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	if resp.StatusCode >= 400 {
		return safeRequestError(responseBody)
	}
	if opts.outputPath != "" {
		if err := os.WriteFile(opts.outputPath, responseBody, 0o600); err != nil {
			return fmt.Errorf("write output: %w", err)
		}
		return nil
	}
	if len(responseBody) == 0 {
		return nil
	}
	if opts.rawOutput {
		_, err = streams.Stdout.Write(responseBody)
		return err
	}
	formatted := formatJSON(responseBody, cfg.compact)
	_, err = streams.Stdout.Write(formatted)
	return err
}

func safeRequestError(responseBody []byte) error {
	payload := apiErrorResponse{}
	if err := json.Unmarshal(responseBody, &payload); err == nil {
		details := make([]string, 0, 3)
		if code := strings.TrimSpace(payload.Code); code != "" {
			details = append(details, code)
		}
		message := strings.TrimSpace(payload.Message)
		if message == "" {
			message = strings.TrimSpace(payload.Detail)
		}
		if message != "" {
			details = append(details, message)
		}
		if upgradeURL := strings.TrimSpace(payload.UpgradeURL); upgradeURL != "" {
			details = append(details, "Upgrade: "+upgradeURL)
		}
		if len(details) > 0 {
			return errors.New("Rowset couldn't complete the request — " + strings.Join(details, " — "))
		}
	}
	return errors.New("Rowset couldn't complete the request. Check the command and try again.")
}

func buildEndpoint(apiBase string, path string, query url.Values, allowAbsolute bool) (string, error) {
	if isAbsoluteHTTPURL(path) {
		if !allowAbsolute {
			return "", errors.New("absolute request URLs require --no-auth")
		}
		parsed, err := url.Parse(path)
		if err != nil {
			return "", err
		}
		if query != nil {
			values := parsed.Query()
			for key, rawValues := range query {
				for _, value := range rawValues {
					values.Add(key, value)
				}
			}
			parsed.RawQuery = values.Encode()
		}
		return parsed.String(), nil
	}
	if strings.TrimSpace(apiBase) == "" {
		return "", errors.New("ROWSET_API_BASE or --api-base is required")
	}
	base := strings.TrimRight(apiBase, "/")
	cleanPath := "/" + strings.TrimLeft(path, "/")
	parsed, err := url.Parse(base + cleanPath)
	if err != nil {
		return "", err
	}
	if query != nil {
		parsed.RawQuery = query.Encode()
	}
	return parsed.String(), nil
}

func isAbsoluteHTTPURL(rawURL string) bool {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return false
	}
	return parsed.IsAbs() && (strings.EqualFold(parsed.Scheme, "http") || strings.EqualFold(parsed.Scheme, "https"))
}

func apiPath(parts ...string) string {
	escaped := make([]string, 0, len(parts))
	for _, part := range parts {
		for _, segment := range strings.Split(part, "/") {
			if segment == "" {
				continue
			}
			escaped = append(escaped, url.PathEscape(segment))
		}
	}
	return "/" + strings.Join(escaped, "/")
}

func newFlagSet(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	return fs
}

func envOrDefault(name string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	return value
}

func paginationFlags(fs *flag.FlagSet, defaultLimit int, defaultOffset int) (*int, *int) {
	limit := fs.Int("limit", defaultLimit, "page limit")
	offset := fs.Int("offset", defaultOffset, "page offset")
	return limit, offset
}

func paginationValues(limit int, offset int) url.Values {
	values := url.Values{}
	values.Set("limit", strconv.Itoa(limit))
	values.Set("offset", strconv.Itoa(offset))
	return values
}

func addQuery(values url.Values, key string, value string) {
	if value != "" {
		values.Set(key, value)
	}
}

func flagWasSet(fs *flag.FlagSet, name string) bool {
	wasSet := false
	fs.Visit(func(flag *flag.Flag) {
		if flag.Name == name {
			wasSet = true
		}
	})
	return wasSet
}

func splitCSV(value string) []string {
	parts := strings.Split(value, ",")
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		item := strings.TrimSpace(part)
		if item != "" {
			out = append(out, item)
		}
	}
	return out
}

func parseRows(rowsJSON string, rowValues repeatedStrings) ([]any, error) {
	var rows []any
	if rowsJSON != "" {
		var parsed []any
		if err := json.Unmarshal([]byte(rowsJSON), &parsed); err != nil {
			return nil, fmt.Errorf("--rows must be a JSON array: %w", err)
		}
		rows = append(rows, parsed...)
	}
	for _, raw := range rowValues {
		row, err := parseJSONObject(raw, "--row")
		if err != nil {
			return nil, err
		}
		rows = append(rows, row)
	}
	if rows == nil {
		return nil, nil
	}
	return rows, nil
}

func parseJSONObject(raw string, flagName string) (map[string]any, error) {
	var value map[string]any
	if err := json.Unmarshal([]byte(raw), &value); err != nil {
		return nil, fmt.Errorf("%s must be a JSON object: %w", flagName, err)
	}
	if value == nil {
		return nil, fmt.Errorf("%s must be a JSON object", flagName)
	}
	return value, nil
}

func parseJSONValue(raw string, flagName string) (any, error) {
	var value any
	if err := json.Unmarshal([]byte(raw), &value); err != nil {
		return nil, fmt.Errorf("%s must be valid JSON: %w", flagName, err)
	}
	return value, nil
}

func parseMaybeJSON(raw string, flagName string) (any, error) {
	trimmed := strings.TrimSpace(raw)
	if strings.HasPrefix(trimmed, "{") || strings.HasPrefix(trimmed, "[") || strings.HasPrefix(trimmed, `"`) {
		return parseJSONValue(trimmed, flagName)
	}
	return raw, nil
}

func formatJSON(data []byte, compact bool) []byte {
	var formatted bytes.Buffer
	var err error
	if compact {
		err = json.Compact(&formatted, data)
	} else {
		err = json.Indent(&formatted, data, "", "  ")
	}
	if err != nil {
		if len(data) > 0 && data[len(data)-1] != '\n' {
			return append(data, '\n')
		}
		return data
	}
	formatted.WriteByte('\n')
	return formatted.Bytes()
}
