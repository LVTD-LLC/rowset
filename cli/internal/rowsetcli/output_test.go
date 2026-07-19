package rowsetcli

import (
	"net/http"
	"os"
	"path/filepath"
	"testing"
)

func TestCompactJSONOutput(t *testing.T) {
	stdout, stderr := runAgainstServer(
		t,
		[]string{"--compact", "user", "info"},
		func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"status":"ok","nested":{"value":1}}`))
		},
	)

	if stderr != "" {
		t.Fatalf("stderr should be empty, got %q", stderr)
	}
	if got, want := stdout, "{\"status\":\"ok\",\"nested\":{\"value\":1}}\n"; got != want {
		t.Fatalf("compact output mismatch: got %q want %q", got, want)
	}
}

func TestCompactDoesNotChangeRawOutputBytes(t *testing.T) {
	rawBytes := []byte("{ \"raw\": true }\n\x00binary\xff")
	tests := []struct {
		name        string
		args        []string
		wantPath    string
		wantQuery   string
		writeToFile bool
	}{
		{
			name:     "export stdout",
			args:     []string{"export", "dataset-key", "csv"},
			wantPath: "/api/datasets/dataset-key/export.csv",
		},
		{
			name:        "export file",
			args:        []string{"export", "dataset-key", "csv"},
			wantPath:    "/api/datasets/dataset-key/export.csv",
			writeToFile: true,
		},
		{
			name:      "asset content stdout",
			args:      []string{"asset", "content", "dataset-key", "asset-key", "--variant", "thumbnail"},
			wantPath:  "/api/datasets/dataset-key/assets/asset-key/content",
			wantQuery: "variant=thumbnail",
		},
		{
			name:        "asset content file",
			args:        []string{"asset", "content", "dataset-key", "asset-key"},
			wantPath:    "/api/datasets/dataset-key/assets/asset-key/content",
			wantQuery:   "variant=original",
			writeToFile: true,
		},
		{
			name:        "request file",
			args:        []string{"request", "GET", "/raw"},
			wantPath:    "/api/raw",
			writeToFile: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			args := append([]string{"--compact"}, tt.args...)
			var outputPath string
			if tt.writeToFile {
				outputPath = filepath.Join(t.TempDir(), "out.bin")
				args = append(args, "--output", outputPath)
			}

			stdout, stderr := runAgainstServer(t, args, func(w http.ResponseWriter, r *http.Request) {
				if r.Method != http.MethodGet {
					t.Fatalf("method mismatch: got %s", r.Method)
				}
				if r.URL.Path != tt.wantPath {
					t.Fatalf("path mismatch: got %s want %s", r.URL.Path, tt.wantPath)
				}
				if r.URL.RawQuery != tt.wantQuery {
					t.Fatalf("query mismatch: got %q want %q", r.URL.RawQuery, tt.wantQuery)
				}
				if r.Header.Get("Authorization") != "Bearer test-key" {
					t.Fatalf("missing bearer auth")
				}
				_, _ = w.Write(rawBytes)
			})

			if stderr != "" {
				t.Fatalf("stderr should be empty, got %q", stderr)
			}
			got := []byte(stdout)
			if tt.writeToFile {
				var err error
				got, err = os.ReadFile(outputPath)
				if err != nil {
					t.Fatalf("read output: %v", err)
				}
				if stdout != "" {
					t.Fatalf("stdout should be empty for file output, got %q", stdout)
				}
			}
			if string(got) != string(rawBytes) {
				t.Fatalf("raw output changed: got %q want %q", got, rawBytes)
			}
		})
	}
}
