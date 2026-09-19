package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptrace"
	"os"
	"path/filepath"
	"testing"
)

type xbarFakeRoundTripper func(*http.Request) (*http.Response, error)

func (f xbarFakeRoundTripper) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestXBarDiagnosticsRecordsOnlyWrittenTeslaRequests(t *testing.T) {
	directory := t.TempDir()
	xbarRecordAPI(directory, 10)
	xbarRecordAPI(directory, 20)
	xbarRecordAPI(directory, 15)
	read := func() []float64 {
		raw, err := os.ReadFile(filepath.Join(directory, "diagnostics.json"))
		if err != nil {
			t.Fatal(err)
		}
		var data map[string][]float64
		if err := json.Unmarshal(raw, &data); err != nil {
			t.Fatal(err)
		}
		return data["tesla_api_calls"]
	}
	if got := read(); len(got) != 2 || got[0] != 20 || got[1] != 15 {
		t.Fatal(got)
	}
	failed := false
	transport := xbarDiagnosticTransport{directory: directory, base: xbarFakeRoundTripper(func(r *http.Request) (*http.Response, error) {
		if trace := httptrace.ContextClientTrace(r.Context()); trace != nil {
			info := httptrace.WroteRequestInfo{}
			if failed {
				info.Err = errors.New("not sent")
			}
			trace.WroteRequest(info)
		}
		return &http.Response{StatusCode: 403}, nil
	})}
	request, _ := http.NewRequest("POST", "https://fleet-api.prd.eu.vn.cloud.tesla.com/example", nil)
	_, _ = transport.RoundTrip(request)
	got := read()
	if len(got) != 2 || got[0] <= 20 || got[1] != 20 {
		t.Fatal(got)
	}
	failed = true
	_, _ = transport.RoundTrip(request)
	other, _ := http.NewRequest("GET", "https://example.com", nil)
	_, _ = transport.RoundTrip(other)
	if latest := read(); latest[0] != got[0] || latest[1] != got[1] {
		t.Fatal(latest)
	}
	stat, _ := os.Stat(filepath.Join(directory, "diagnostics.json"))
	if stat.Mode().Perm() != 0600 {
		t.Fatal(stat.Mode())
	}
}
