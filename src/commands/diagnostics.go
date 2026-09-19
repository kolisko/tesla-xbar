package main

// Observe requests actually written by Tesla's SDK, including its session
// negotiation. Store timestamps only; never URLs, headers, tokens or bodies.
import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptrace"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"
)

func xbarRecordAPI(directory string, at float64) {
	if directory == "" {
		return
	}
	lock, err := os.OpenFile(filepath.Join(directory, "diagnostics.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return
	}
	defer lock.Close()
	if syscall.Flock(int(lock.Fd()), syscall.LOCK_EX) != nil {
		return
	}
	defer syscall.Flock(int(lock.Fd()), syscall.LOCK_UN)
	data := map[string][]float64{}
	if file, err := os.Open(filepath.Join(directory, "diagnostics.json")); err == nil {
		_ = json.NewDecoder(io.LimitReader(file, 4096)).Decode(&data)
		file.Close()
	}
	if data == nil {
		data = map[string][]float64{}
	}
	data["tesla_api_calls"] = append(data["tesla_api_calls"], at)
	for _, key := range []string{"plugin_runs", "tesla_api_calls"} {
		sort.Sort(sort.Reverse(sort.Float64Slice(data[key])))
		if len(data[key]) > 2 {
			data[key] = data[key][:2]
		}
	}
	file, err := os.CreateTemp(directory, ".diagnostics-")
	if err != nil {
		return
	}
	defer os.Remove(file.Name())
	err = json.NewEncoder(file).Encode(data)
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err == nil && closeErr == nil {
		_ = os.Rename(file.Name(), filepath.Join(directory, "diagnostics.json"))
	}
}

type xbarDiagnosticTransport struct {
	base      http.RoundTripper
	directory string
}

func (t xbarDiagnosticTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	host := request.URL.Hostname()
	if !strings.HasSuffix(host, ".tesla.com") && !strings.HasSuffix(host, ".tesla.cn") && !strings.HasSuffix(host, ".teslamotors.com") {
		return t.base.RoundTrip(request)
	}
	trace := &httptrace.ClientTrace{WroteRequest: func(info httptrace.WroteRequestInfo) {
		if info.Err == nil {
			xbarRecordAPI(t.directory, float64(time.Now().UnixNano())/1e9)
		}
	}}
	return t.base.RoundTrip(request.WithContext(httptrace.WithClientTrace(request.Context(), trace)))
}

func init() {
	if directory := os.Getenv("TESLA_XBAR_DIAGNOSTICS_DIR"); directory != "" {
		http.DefaultTransport = xbarDiagnosticTransport{base: http.DefaultTransport, directory: directory}
	}
}
