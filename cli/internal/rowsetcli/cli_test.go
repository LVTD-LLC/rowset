package rowsetcli

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
)

type requestCapture struct {
	method string
	path   string
	query  string
	auth   string
	body   map[string]any
}

func runAgainstServer(
	t *testing.T,
	args []string,
	handler http.HandlerFunc,
) (stdout string, stderr string) {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)

	t.Setenv("ROWSET_API_BASE", server.URL+"/api/")
	t.Setenv("ROWSET_API_KEY", "test-key")

	var out bytes.Buffer
	var errOut bytes.Buffer
	err := Run(context.Background(), IO{
		Stdout: &out,
		Stderr: &errOut,
		Stdin:  strings.NewReader(""),
	}, args)
	if err != nil {
		t.Fatalf("Run returned error: %v\nstderr:\n%s", err, errOut.String())
	}
	return out.String(), errOut.String()
}

func expectJSONRequest(
	t *testing.T,
	want requestCapture,
) http.HandlerFunc {
	t.Helper()
	return func(w http.ResponseWriter, r *http.Request) {
		got := requestCapture{
			method: r.Method,
			path:   r.URL.Path,
			query:  r.URL.RawQuery,
			auth:   r.Header.Get("Authorization"),
			body:   map[string]any{},
		}
		if r.Body != nil {
			defer r.Body.Close()
			if r.ContentLength != 0 {
				if err := json.NewDecoder(r.Body).Decode(&got.body); err != nil {
					t.Fatalf("request body is not JSON: %v", err)
				}
			}
		}

		if got.method != want.method {
			t.Fatalf("method mismatch: got %s want %s", got.method, want.method)
		}
		if got.path != want.path {
			t.Fatalf("path mismatch: got %s want %s", got.path, want.path)
		}
		if got.query != want.query {
			t.Fatalf("query mismatch: got %q want %q", got.query, want.query)
		}
		if want.auth != "" && got.auth != want.auth {
			t.Fatalf("auth mismatch: got %q want %q", got.auth, want.auth)
		}
		if want.body != nil && !reflect.DeepEqual(got.body, want.body) {
			t.Fatalf("body mismatch:\ngot  %#v\nwant %#v", got.body, want.body)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	}
}

func TestCommandRoutesCoverRowsetOperations(t *testing.T) {
	tests := []struct {
		name string
		args []string
		want requestCapture
	}{
		{
			name: "capabilities",
			args: []string{"capabilities"},
			want: requestCapture{method: http.MethodGet, path: "/api/capabilities"},
		},
		{
			name: "user info",
			args: []string{"user", "info"},
			want: requestCapture{method: http.MethodGet, path: "/api/user", auth: "Bearer test-key"},
		},
		{
			name: "feedback submit",
			args: []string{"feedback", "submit", "--feedback", "Needs CLI docs", "--page", "/docs", "--context", `{"area":"cli"}`},
			want: requestCapture{
				method: http.MethodPost,
				path:   "/api/feedback",
				auth:   "Bearer test-key",
				body: map[string]any{
					"feedback": "Needs CLI docs",
					"page":     "/docs",
					"context":  map[string]any{"area": "cli"},
				},
			},
		},
		{
			name: "api key create",
			args: []string{"api-key", "create", "--name", "Codex", "--access-level", "read"},
			want: requestCapture{
				method: http.MethodPost,
				path:   "/api/agent-api-keys",
				auth:   "Bearer test-key",
				body:   map[string]any{"name": "Codex", "access_level": "read"},
			},
		},
		{
			name: "project list",
			args: []string{"project", "list", "--query", "launch", "--limit", "25", "--offset", "50"},
			want: requestCapture{
				method: http.MethodGet,
				path:   "/api/projects",
				query:  "limit=25&offset=50&query=launch",
				auth:   "Bearer test-key",
			},
		},
		{
			name: "project create",
			args: []string{"project", "create", "--name", "Launch", "--description", "Ops", "--metadata", `{"repo":"rowset"}`},
			want: requestCapture{
				method: http.MethodPost,
				path:   "/api/projects",
				auth:   "Bearer test-key",
				body: map[string]any{
					"name":        "Launch",
					"description": "Ops",
					"metadata":    map[string]any{"repo": "rowset"},
				},
			},
		},
		{
			name: "project get",
			args: []string{"project", "get", "project-key", "--limit", "5", "--offset", "10"},
			want: requestCapture{
				method: http.MethodGet,
				path:   "/api/projects/project-key",
				query:  "limit=5&offset=10",
				auth:   "Bearer test-key",
			},
		},
		{
			name: "project update",
			args: []string{"project", "update", "project-key", "--name", "Launch ops", "--description", ""},
			want: requestCapture{
				method: http.MethodPatch,
				path:   "/api/projects/project-key",
				auth:   "Bearer test-key",
				body:   map[string]any{"name": "Launch ops", "description": ""},
			},
		},
		{
			name: "project metadata",
			args: []string{"project", "metadata", "project-key", "--metadata", `{"notion":"url"}`},
			want: requestCapture{
				method: http.MethodPatch,
				path:   "/api/projects/project-key/metadata",
				auth:   "Bearer test-key",
				body:   map[string]any{"metadata": map[string]any{"notion": "url"}},
			},
		},
		{
			name: "project section list",
			args: []string{"project", "section", "list", "project-key", "--limit", "5"},
			want: requestCapture{
				method: http.MethodGet,
				path:   "/api/projects/project-key/sections",
				query:  "limit=5&offset=0",
				auth:   "Bearer test-key",
			},
		},
		{
			name: "project section create",
			args: []string{"project", "section", "create", "project-key", "--name", "Backlog", "--metadata", `{"goal":"ship"}`},
			want: requestCapture{
				method: http.MethodPost,
				path:   "/api/projects/project-key/sections",
				auth:   "Bearer test-key",
				body:   map[string]any{"name": "Backlog", "metadata": map[string]any{"goal": "ship"}},
			},
		},
		{
			name: "project section update",
			args: []string{"project", "section", "update", "project-key", "section-key", "--description", "Ready"},
			want: requestCapture{
				method: http.MethodPatch,
				path:   "/api/projects/project-key/sections/section-key",
				auth:   "Bearer test-key",
				body:   map[string]any{"description": "Ready"},
			},
		},
		{
			name: "project section archive",
			args: []string{"project", "section", "archive", "project-key", "section-key"},
			want: requestCapture{
				method: http.MethodDelete,
				path:   "/api/projects/project-key/sections/section-key",
				auth:   "Bearer test-key",
			},
		},
		{
			name: "project archive",
			args: []string{"project", "archive", "project-key"},
			want: requestCapture{method: http.MethodDelete, path: "/api/projects/project-key", auth: "Bearer test-key"},
		},
		{
			name: "dataset list",
			args: []string{
				"dataset", "list",
				"--query", "feature",
				"--project-key", "project-key",
				"--section-key", "section-key",
				"--header-contains", "status",
				"--status", "ready",
				"--updated-after", "2026-06-01",
				"--limit", "10",
				"--offset", "20",
			},
			want: requestCapture{
				method: http.MethodGet,
				path:   "/api/datasets",
				query:  "header_contains=status&limit=10&offset=20&project_key=project-key&query=feature&section_key=section-key&status=ready&updated_after=2026-06-01",
				auth:   "Bearer test-key",
			},
		},
		{
			name: "dataset archived",
			args: []string{"dataset", "archived", "--limit", "10", "--offset", "20"},
			want: requestCapture{method: http.MethodGet, path: "/api/datasets/archived", query: "limit=10&offset=20", auth: "Bearer test-key"},
		},
		{
			name: "dataset get",
			args: []string{"dataset", "get", "dataset-key"},
			want: requestCapture{method: http.MethodGet, path: "/api/datasets/dataset-key", auth: "Bearer test-key"},
		},
		{
			name: "dataset create",
			args: []string{
				"dataset", "create",
				"--name", "Products",
				"--headers", "sku,name,price,tags",
				"--index-column", "sku",
				"--row", `{"sku":"A-1","name":"Adapter","price":19.99,"tags":"hardware, usb-c"}`,
				"--column-types", `{"price":"currency","tags":"tags"}`,
				"--project-key", "project-key",
			},
			want: requestCapture{
				method: http.MethodPost,
				path:   "/api/datasets",
				auth:   "Bearer test-key",
				body: map[string]any{
					"name":         "Products",
					"headers":      []any{"sku", "name", "price", "tags"},
					"index_column": "sku",
					"rows": []any{
						map[string]any{"sku": "A-1", "name": "Adapter", "price": 19.99, "tags": "hardware, usb-c"},
					},
					"column_types": map[string]any{"price": "currency", "tags": "tags"},
					"project_key":  "project-key",
				},
			},
		},
		{
			name: "dataset metadata",
			args: []string{"dataset", "metadata", "dataset-key", "--description", "Tasks", "--instructions", "Keep task_id stable", "--metadata", `{"order":["todo"]}`},
			want: requestCapture{
				method: http.MethodPatch,
				path:   "/api/datasets/dataset-key/metadata",
				auth:   "Bearer test-key",
				body: map[string]any{
					"description":  "Tasks",
					"instructions": "Keep task_id stable",
					"metadata":     map[string]any{"order": []any{"todo"}},
				},
			},
		},
		{
			name: "dataset column types",
			args: []string{"dataset", "column-types", "dataset-key", "--column-types", `{"status":{"type":"choice","choices":["todo","done"]}}`},
			want: requestCapture{
				method: http.MethodPatch,
				path:   "/api/datasets/dataset-key/column-types",
				auth:   "Bearer test-key",
				body: map[string]any{
					"column_types": map[string]any{
						"status": map[string]any{"type": "choice", "choices": []any{"todo", "done"}},
					},
				},
			},
		},
		{
			name: "dataset project assign",
			args: []string{"dataset", "project", "dataset-key", "--project-key", "project-key", "--section-key", "section-key"},
			want: requestCapture{
				method: http.MethodPatch,
				path:   "/api/datasets/dataset-key/project",
				auth:   "Bearer test-key",
				body:   map[string]any{"project_key": "project-key", "section_key": "section-key"},
			},
		},
		{
			name: "dataset project clear",
			args: []string{"dataset", "project", "dataset-key", "--clear"},
			want: requestCapture{
				method: http.MethodPatch,
				path:   "/api/datasets/dataset-key/project",
				auth:   "Bearer test-key",
				body:   map[string]any{"project_key": nil},
			},
		},
		{
			name: "dataset archive",
			args: []string{"dataset", "archive", "dataset-key"},
			want: requestCapture{method: http.MethodDelete, path: "/api/datasets/dataset-key", auth: "Bearer test-key"},
		},
		{
			name: "dataset restore",
			args: []string{"dataset", "restore", "dataset-key"},
			want: requestCapture{method: http.MethodPost, path: "/api/datasets/dataset-key/restore", auth: "Bearer test-key"},
		},
		{
			name: "preview update",
			args: []string{"preview", "update", "dataset-key", "--enabled", "true", "--page-size", "25", "--password", "secret"},
			want: requestCapture{
				method: http.MethodPatch,
				path:   "/api/datasets/dataset-key/public-preview",
				auth:   "Bearer test-key",
				body:   map[string]any{"public_enabled": true, "public_page_size": float64(25), "public_password": "secret"},
			},
		},
		{
			name: "column add",
			args: []string{"column", "add", "dataset-key", "--name", "status", "--default-value", "todo", "--column-type", `{"type":"choice","choices":["todo","done"]}`},
			want: requestCapture{
				method: http.MethodPost,
				path:   "/api/datasets/dataset-key/columns",
				auth:   "Bearer test-key",
				body: map[string]any{
					"name":          "status",
					"default_value": "todo",
					"column_type":   map[string]any{"type": "choice", "choices": []any{"todo", "done"}},
				},
			},
		},
		{
			name: "column rename",
			args: []string{"column", "rename", "dataset-key", "old", "new"},
			want: requestCapture{method: http.MethodPost, path: "/api/datasets/dataset-key/columns/rename", auth: "Bearer test-key", body: map[string]any{"old_name": "old", "new_name": "new"}},
		},
		{
			name: "column drop",
			args: []string{"column", "drop", "dataset-key", "notes"},
			want: requestCapture{method: http.MethodPost, path: "/api/datasets/dataset-key/columns/drop", auth: "Bearer test-key", body: map[string]any{"name": "notes"}},
		},
		{
			name: "column reorder",
			args: []string{"column", "reorder", "dataset-key", "--headers", "sku,name,price"},
			want: requestCapture{method: http.MethodPost, path: "/api/datasets/dataset-key/columns/reorder", auth: "Bearer test-key", body: map[string]any{"headers": []any{"sku", "name", "price"}}},
		},
		{
			name: "relationship list",
			args: []string{"relationship", "list", "dataset-key"},
			want: requestCapture{method: http.MethodGet, path: "/api/datasets/dataset-key/relationships", auth: "Bearer test-key"},
		},
		{
			name: "relationship create",
			args: []string{"relationship", "create", "dataset-key", "--source-column", "person_id", "--target-dataset-key", "people-key", "--name", "Message person", "--enforce-integrity", "false"},
			want: requestCapture{
				method: http.MethodPost,
				path:   "/api/datasets/dataset-key/relationships",
				auth:   "Bearer test-key",
				body: map[string]any{
					"source_column":      "person_id",
					"target_dataset_key": "people-key",
					"name":               "Message person",
					"enforce_integrity":  false,
				},
			},
		},
		{
			name: "relationship resolve",
			args: []string{"relationship", "resolve", "dataset-key", "relationship-key", "--source-index-value", "M-1"},
			want: requestCapture{
				method: http.MethodGet,
				path:   "/api/datasets/dataset-key/relationships/relationship-key/resolve",
				query:  "source_index_value=M-1",
				auth:   "Bearer test-key",
			},
		},
		{
			name: "relationship delete",
			args: []string{"relationship", "delete", "dataset-key", "relationship-key"},
			want: requestCapture{method: http.MethodDelete, path: "/api/datasets/dataset-key/relationships/relationship-key", auth: "Bearer test-key"},
		},
		{
			name: "row list",
			args: []string{"row", "list", "dataset-key", "--limit", "5", "--offset", "10", "--query", "Ada", "--filters", `{"active":true}`, "--sort", "name", "--direction", "desc"},
			want: requestCapture{
				method: http.MethodGet,
				path:   "/api/datasets/dataset-key/rows",
				query:  "direction=desc&filters=%7B%22active%22%3Atrue%7D&limit=5&offset=10&query=Ada&sort=name",
				auth:   "Bearer test-key",
			},
		},
		{
			name: "row search across datasets",
			args: []string{"row", "search", "renewal risks", "--filters", `{"status":"Ready"}`, "--filter-operators", `{"status":"is"}`, "--dataset-key", "dataset-key", "--archived", "false", "--sort", "rank", "--limit", "10"},
			want: requestCapture{
				method: http.MethodPost,
				path:   "/api/search",
				auth:   "Bearer test-key",
				body: map[string]any{
					"query":            "renewal risks",
					"filters":          map[string]any{"status": "Ready"},
					"filter_operators": map[string]any{"status": "is"},
					"dataset_key":      "dataset-key",
					"archived":         false,
					"sort":             "rank",
					"limit":            float64(10),
				},
			},
		},
		{
			name: "row search dataset",
			args: []string{"row", "search-dataset", "dataset-key", "stale vectors", "--filters", `{"status":"Ready"}`, "--limit", "3"},
			want: requestCapture{
				method: http.MethodPost,
				path:   "/api/datasets/dataset-key/search",
				auth:   "Bearer test-key",
				body:   map[string]any{"query": "stale vectors", "filters": map[string]any{"status": "Ready"}, "limit": float64(3)},
			},
		},
		{
			name: "row get",
			args: []string{"row", "get", "dataset-key", "7"},
			want: requestCapture{method: http.MethodGet, path: "/api/datasets/dataset-key/rows/7", auth: "Bearer test-key"},
		},
		{
			name: "row get by index",
			args: []string{"row", "get-by-index", "dataset-key", "A-1"},
			want: requestCapture{method: http.MethodGet, path: "/api/datasets/dataset-key/rows/by-index", query: "index_value=A-1", auth: "Bearer test-key"},
		},
		{
			name: "row create",
			args: []string{"row", "create", "dataset-key", "--data", `{"sku":"A-1"}`},
			want: requestCapture{method: http.MethodPost, path: "/api/datasets/dataset-key/rows", auth: "Bearer test-key", body: map[string]any{"data": map[string]any{"sku": "A-1"}}},
		},
		{
			name: "row update",
			args: []string{"row", "update", "dataset-key", "7", "--data", `{"name":"Adapter"}`},
			want: requestCapture{method: http.MethodPatch, path: "/api/datasets/dataset-key/rows/7", auth: "Bearer test-key", body: map[string]any{"data": map[string]any{"name": "Adapter"}}},
		},
		{
			name: "row update by index",
			args: []string{"row", "update-by-index", "dataset-key", "A-1", "--data", `{"name":"Adapter"}`},
			want: requestCapture{method: http.MethodPatch, path: "/api/datasets/dataset-key/rows/by-index", query: "index_value=A-1", auth: "Bearer test-key", body: map[string]any{"data": map[string]any{"name": "Adapter"}}},
		},
		{
			name: "row delete",
			args: []string{"row", "delete", "dataset-key", "7"},
			want: requestCapture{method: http.MethodDelete, path: "/api/datasets/dataset-key/rows/7", auth: "Bearer test-key"},
		},
		{
			name: "asset get",
			args: []string{"asset", "get", "dataset-key", "asset-key"},
			want: requestCapture{method: http.MethodGet, path: "/api/datasets/dataset-key/assets/asset-key", auth: "Bearer test-key"},
		},
		{
			name: "request escape hatch",
			args: []string{"request", "PATCH", "/datasets/dataset-key/public-preview", "--json", `{"public_enabled":false}`},
			want: requestCapture{
				method: http.MethodPatch,
				path:   "/api/datasets/dataset-key/public-preview",
				auth:   "Bearer test-key",
				body:   map[string]any{"public_enabled": false},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			stdout, stderr := runAgainstServer(t, tt.args, expectJSONRequest(t, tt.want))
			if stderr != "" {
				t.Fatalf("stderr should be empty, got %q", stderr)
			}
			if !strings.Contains(stdout, `"status": "ok"`) {
				t.Fatalf("expected pretty JSON response, got %q", stdout)
			}
		})
	}
}

func TestRunUsesProductionAPIBaseByDefault(t *testing.T) {
	t.Setenv("ROWSET_API_BASE", "")
	t.Setenv("ROWSET_API_KEY", "")

	var out bytes.Buffer
	var errOut bytes.Buffer
	err := Run(context.Background(), IO{
		Stdout: &out,
		Stderr: &errOut,
		Stdin:  strings.NewReader(""),
	}, []string{"user", "info"})

	if err == nil {
		t.Fatal("expected missing API key error")
	}
	if !strings.Contains(err.Error(), "ROWSET_API_KEY") {
		t.Fatalf("expected ROWSET_API_KEY guidance, got %v", err)
	}
}

func TestHelpVersionAndUsageUseRowsetCommand(t *testing.T) {
	var versionOut bytes.Buffer
	err := Run(context.Background(), IO{
		Stdout: &versionOut,
		Stderr: &bytes.Buffer{},
		Stdin:  strings.NewReader(""),
	}, []string{"--version"})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
	if got, want := versionOut.String(), "rowset dev\n"; got != want {
		t.Fatalf("version output mismatch: got %q want %q", got, want)
	}

	var helpOut bytes.Buffer
	err = Run(context.Background(), IO{
		Stdout: &helpOut,
		Stderr: &bytes.Buffer{},
		Stdin:  strings.NewReader(""),
	}, []string{"--help"})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
	if !strings.Contains(helpOut.String(), "rowset is the Rowset REST CLI.") {
		t.Fatalf("help should name rowset command, got %q", helpOut.String())
	}
	if strings.Contains(helpOut.String(), "rowset-cli") {
		t.Fatalf("help should not tell users to run rowset-cli: %q", helpOut.String())
	}

	err = Run(context.Background(), IO{
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
		Stdin:  strings.NewReader(""),
	}, []string{"user"})
	if err == nil {
		t.Fatal("expected usage error")
	}
	if got, want := err.Error(), "usage: rowset user info"; got != want {
		t.Fatalf("usage error mismatch: got %q want %q", got, want)
	}
}

func TestRawRequestRejectsAuthenticatedAbsoluteURLs(t *testing.T) {
	t.Setenv("ROWSET_API_BASE", "https://rowset.example/api/")
	t.Setenv("ROWSET_API_KEY", "test-key")

	var called atomic.Bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called.Store(true)
		_, _ = w.Write([]byte(`{"status":"unexpected"}`))
	}))
	t.Cleanup(server.Close)

	err := Run(context.Background(), IO{
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
		Stdin:  strings.NewReader(""),
	}, []string{"request", "GET", server.URL + "/capture"})
	if err == nil {
		t.Fatal("expected authenticated absolute URL request to fail")
	}
	if !strings.Contains(err.Error(), "--no-auth") {
		t.Fatalf("expected --no-auth guidance, got %v", err)
	}
	if called.Load() {
		t.Fatal("absolute URL server should not receive authenticated request")
	}
}

func TestRawRequestAllowsAbsoluteURLsWithoutAuth(t *testing.T) {
	t.Setenv("ROWSET_API_BASE", "")
	t.Setenv("ROWSET_API_KEY", "test-key")

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			t.Fatalf("method mismatch: got %s", r.Method)
		}
		if r.URL.Path != "/public" {
			t.Fatalf("path mismatch: got %s", r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "" {
			t.Fatalf("Authorization header should be empty, got %q", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	}))
	t.Cleanup(server.Close)

	var out bytes.Buffer
	err := Run(context.Background(), IO{
		Stdout: &out,
		Stderr: &bytes.Buffer{},
		Stdin:  strings.NewReader(""),
	}, []string{"request", "GET", server.URL + "/public", "--no-auth"})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
	if !strings.Contains(out.String(), `"status": "ok"`) {
		t.Fatalf("expected pretty JSON response, got %q", out.String())
	}
}

func TestTrialExpiredErrorIncludesUpgradeGuidance(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusPaymentRequired)
		_, _ = w.Write([]byte(`{"code":"TRIAL_EXPIRED","message":"Your Rowset trial has ended. Upgrade to continue using the API, CLI, and MCP.","upgrade_url":"https://rowset.example/pricing"}`))
	}))
	t.Cleanup(server.Close)
	t.Setenv("ROWSET_API_BASE", server.URL+"/api/")
	t.Setenv("ROWSET_API_KEY", "test-key")

	err := Run(context.Background(), IO{
		Stdout: &bytes.Buffer{},
		Stderr: &bytes.Buffer{},
		Stdin:  strings.NewReader(""),
	}, []string{"user", "info"})

	if err == nil {
		t.Fatal("expected trial expiration to fail")
	}
	if !strings.Contains(err.Error(), "TRIAL_EXPIRED") {
		t.Fatalf("expected stable error code, got %v", err)
	}
	if !strings.Contains(err.Error(), "https://rowset.example/pricing") ||
		strings.Contains(err.Error(), "https://rowset.example/pricing/") {
		t.Fatalf("expected pricing upgrade link, got %v", err)
	}
}

func TestGlobalFlagsOverrideEnvironment(t *testing.T) {
	t.Setenv("ROWSET_API_BASE", "https://wrong.example/api/")
	t.Setenv("ROWSET_API_KEY", "wrong-key")
	t.Setenv("CUSTOM_ROWSET_KEY", "custom-key")

	server := httptest.NewServer(expectJSONRequest(t, requestCapture{
		method: http.MethodGet,
		path:   "/api/user",
		auth:   "Bearer custom-key",
	}))
	t.Cleanup(server.Close)

	var out bytes.Buffer
	err := Run(context.Background(), IO{
		Stdout: &out,
		Stderr: &bytes.Buffer{},
		Stdin:  strings.NewReader(""),
	}, []string{"--api-base", server.URL + "/api/", "--api-key-env", "CUSTOM_ROWSET_KEY", "user", "info"})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
}

func TestExportAndAssetContentWriteRawBytes(t *testing.T) {
	for _, tt := range []struct {
		name     string
		args     []string
		wantPath string
		query    string
	}{
		{
			name:     "export",
			args:     []string{"export", "dataset-key", "csv", "--output"},
			wantPath: "/api/datasets/dataset-key/export.csv",
		},
		{
			name:     "asset content",
			args:     []string{"asset", "content", "dataset-key", "asset-key", "--variant", "thumbnail", "--output"},
			wantPath: "/api/datasets/dataset-key/assets/asset-key/content",
			query:    "variant=thumbnail",
		},
		{
			name:     "asset content default variant",
			args:     []string{"asset", "content", "dataset-key", "asset-key", "--output"},
			wantPath: "/api/datasets/dataset-key/assets/asset-key/content",
			query:    "variant=original",
		},
	} {
		t.Run(tt.name, func(t *testing.T) {
			outputPath := filepath.Join(t.TempDir(), "out.bin")
			args := append([]string{}, tt.args...)
			args = append(args, outputPath)

			runAgainstServer(t, args, func(w http.ResponseWriter, r *http.Request) {
				if r.Method != http.MethodGet {
					t.Fatalf("method mismatch: got %s", r.Method)
				}
				if r.URL.Path != tt.wantPath {
					t.Fatalf("path mismatch: got %s want %s", r.URL.Path, tt.wantPath)
				}
				if r.URL.RawQuery != tt.query {
					t.Fatalf("query mismatch: got %q want %q", r.URL.RawQuery, tt.query)
				}
				if r.Header.Get("Authorization") != "Bearer test-key" {
					t.Fatalf("missing bearer auth")
				}
				_, _ = w.Write([]byte("raw-bytes"))
			})

			data, err := os.ReadFile(outputPath)
			if err != nil {
				t.Fatalf("read output: %v", err)
			}
			if string(data) != "raw-bytes" {
				t.Fatalf("output mismatch: %q", string(data))
			}
		})
	}
}

func TestAssetAttachReadsAndEncodesLocalImage(t *testing.T) {
	imagePath := filepath.Join(t.TempDir(), "photo.png")
	if err := os.WriteFile(imagePath, []byte("fake-png"), 0o600); err != nil {
		t.Fatalf("write image: %v", err)
	}

	runAgainstServer(t, []string{
		"asset", "attach", "dataset-key",
		"--index-value", "SKU-1",
		"--column", "photo",
		"--file", imagePath,
		"--filename", "photo.png",
		"--content-type", "image/png",
	}, expectJSONRequest(t, requestCapture{
		method: http.MethodPost,
		path:   "/api/datasets/dataset-key/rows/by-index/image",
		query:  "index_value=SKU-1",
		auth:   "Bearer test-key",
		body: map[string]any{
			"column_name":  "photo",
			"image_base64": base64.StdEncoding.EncodeToString([]byte("fake-png")),
			"filename":     "photo.png",
			"content_type": "image/png",
		},
	}))
}

func TestAssetAttachReadsAndEncodesLocalAudio(t *testing.T) {
	audioPath := filepath.Join(t.TempDir(), "clip.wav")
	if err := os.WriteFile(audioPath, []byte("fake-wav"), 0o600); err != nil {
		t.Fatalf("write audio: %v", err)
	}

	runAgainstServer(t, []string{
		"asset", "attach", "dataset-key",
		"--asset-type", "audio",
		"--row-id", "7",
		"--column", "clip",
		"--file", audioPath,
		"--content-type", "audio/wav",
	}, expectJSONRequest(t, requestCapture{
		method: http.MethodPost,
		path:   "/api/datasets/dataset-key/rows/7/audio",
		auth:   "Bearer test-key",
		body: map[string]any{
			"column_name":  "clip",
			"audio_base64": base64.StdEncoding.EncodeToString([]byte("fake-wav")),
			"filename":     "clip.wav",
			"content_type": "audio/wav",
		},
	}))
}
