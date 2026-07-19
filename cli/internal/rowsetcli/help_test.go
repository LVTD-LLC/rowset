package rowsetcli

import (
	"bytes"
	"context"
	"net/http"
	"strings"
	"testing"
)

func TestNestedHelpDoesNotRequireAuthenticationOrNetwork(t *testing.T) {
	t.Setenv("ROWSET_API_BASE", "http://127.0.0.1:1/api/")
	t.Setenv("ROWSET_API_KEY", "")

	tests := []struct {
		name        string
		args        []string
		wantUsage   string
		wantExample string
	}{
		{
			name:        "group",
			args:        []string{"dataset", "--help"},
			wantUsage:   "Usage: rowset dataset <command>",
			wantExample: "rowset dataset get \"{dataset_key}\"",
		},
		{
			name:        "nested group",
			args:        []string{"project", "section", "--help"},
			wantUsage:   "Usage: rowset project section <command>",
			wantExample: "rowset project section list \"{project_key}\"",
		},
		{
			name:        "leaf before arguments",
			args:        []string{"dataset", "search", "--help"},
			wantUsage:   "Usage: rowset dataset search QUERY [flags]",
			wantExample: "rowset dataset search \"launch tasks\" --limit 3",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var out bytes.Buffer
			err := Run(context.Background(), IO{
				Stdout: &out,
				Stderr: &bytes.Buffer{},
				Stdin:  strings.NewReader(""),
			}, tt.args)
			if err != nil {
				t.Fatalf("Run returned error: %v", err)
			}
			if !strings.Contains(out.String(), tt.wantUsage) {
				t.Fatalf("help missing usage %q:\n%s", tt.wantUsage, out.String())
			}
			if !strings.Contains(out.String(), tt.wantExample) {
				t.Fatalf("help missing example %q:\n%s", tt.wantExample, out.String())
			}
		})
	}
}

func TestEveryDocumentedCommandHasHelp(t *testing.T) {
	t.Setenv("ROWSET_API_BASE", "http://127.0.0.1:1/api/")
	t.Setenv("ROWSET_API_KEY", "")

	paths := []string{
		"capabilities", "healthcheck", "user", "user info", "feedback", "feedback submit",
		"api-key", "api-key create", "project", "project list", "project search",
		"project create", "project get", "project update", "project metadata", "project archive",
		"project section", "project section list", "project section create",
		"project section update", "project section archive", "dataset", "dataset list",
		"dataset search", "dataset archived", "dataset get", "dataset create", "dataset metadata",
		"dataset column-types", "dataset project", "dataset archive", "dataset restore", "preview",
		"preview update", "column", "column add", "column rename", "column drop", "column reorder",
		"relationship", "relationship list", "relationship create", "relationship resolve",
		"relationship delete", "row", "row list", "row search", "row search-dataset", "row get",
		"row get-by-index", "row create", "row update", "row update-by-index", "row delete", "asset",
		"asset attach", "asset get", "asset content", "export", "request",
	}

	for _, path := range paths {
		t.Run(path, func(t *testing.T) {
			args := append(strings.Fields(path), "--help")
			var out bytes.Buffer
			err := Run(context.Background(), IO{
				Stdout: &out,
				Stderr: &bytes.Buffer{},
				Stdin:  strings.NewReader(""),
			}, args)
			if err != nil {
				t.Fatalf("Run(%q) returned error: %v", args, err)
			}
			if !strings.Contains(out.String(), "Usage: rowset "+path) {
				t.Fatalf("help missing command usage:\n%s", out.String())
			}
			if !strings.Contains(out.String(), "Example:\n  rowset ") {
				t.Fatalf("help missing example:\n%s", out.String())
			}
		})
	}
}

func TestHelpCommandAcceptsNestedTopic(t *testing.T) {
	var out bytes.Buffer
	err := Run(context.Background(), IO{
		Stdout: &out,
		Stderr: &bytes.Buffer{},
		Stdin:  strings.NewReader(""),
	}, []string{"help", "dataset", "search"})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
	if !strings.Contains(out.String(), "Usage: rowset dataset search QUERY [flags]") {
		t.Fatalf("nested help topic missing usage:\n%s", out.String())
	}
}

func TestHelpFlagCanBeAStringFlagValue(t *testing.T) {
	runAgainstServer(t, []string{"feedback", "submit", "--feedback", "--help"}, expectJSONRequest(t, requestCapture{
		method: http.MethodPost,
		path:   "/api/feedback",
		auth:   "Bearer test-key",
		body:   map[string]any{"feedback": "--help"},
	}))
}

func TestAPIKeyAliasHasNestedHelp(t *testing.T) {
	var out bytes.Buffer
	err := Run(context.Background(), IO{
		Stdout: &out,
		Stderr: &bytes.Buffer{},
		Stdin:  strings.NewReader(""),
	}, []string{"apikey", "create", "--help"})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
	if !strings.Contains(out.String(), "Usage: rowset api-key create") {
		t.Fatalf("alias help missing canonical usage:\n%s", out.String())
	}
}
