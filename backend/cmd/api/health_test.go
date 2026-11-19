package main

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestHealthIsIndependentOfDatabase(t *testing.T) {
	handler := newHandler(func(context.Context) error {
		t.Fatal("liveness consulted the database")
		return nil
	}, time.Second, slog.New(slog.DiscardHandler))

	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	checkResponse(t, response, http.StatusOK, "{\"status\":\"ok\"}\n")
}

func TestReadinessResponsesAndLogging(t *testing.T) {
	const sensitive = "synthetic-private-target"
	for _, tc := range []struct {
		name   string
		err    error
		status int
		body   string
	}{
		{"ready", nil, http.StatusOK, "{\"status\":\"ready\"}\n"},
		{"unavailable", errors.New(sensitive), http.StatusServiceUnavailable, "{\"status\":\"not_ready\"}\n"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var logs bytes.Buffer
			handler := newHandler(func(context.Context) error { return tc.err }, time.Second, slog.New(slog.NewJSONHandler(&logs, nil)))
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/readyz", nil))
			checkResponse(t, response, tc.status, tc.body)
			if strings.Contains(logs.String()+response.Body.String(), sensitive) {
				t.Error("the dependency error escaped into the response or logs")
			}
		})
	}
}

func TestReadinessHonorsDeadlineAndCancellation(t *testing.T) {
	for _, canceled := range []bool{false, true} {
		request := httptest.NewRequest(http.MethodGet, "/readyz", nil)
		wantErr := context.DeadlineExceeded
		cancelRequest := func() {}
		if canceled {
			ctx, cancel := context.WithCancel(request.Context())
			cancelRequest = cancel
			defer cancel()
			request = request.WithContext(ctx)
			wantErr = context.Canceled
		}
		handler := newHandler(func(ctx context.Context) error {
			if _, ok := ctx.Deadline(); !ok && !canceled {
				t.Fatal("readiness check has no deadline")
			}
			cancelRequest()
			<-ctx.Done()
			if !errors.Is(ctx.Err(), wantErr) {
				t.Errorf("context error = %v, want %v", ctx.Err(), wantErr)
			}
			// An adapter's late success cannot turn a canceled probe into a 200.
			return nil
		}, 10*time.Millisecond, slog.New(slog.DiscardHandler))
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		checkResponse(t, response, http.StatusServiceUnavailable, "{\"status\":\"not_ready\"}\n")
	}
}

func TestUnsupportedRoutesAndMethods(t *testing.T) {
	handler := newHandler(func(context.Context) error {
		t.Fatal("unsupported request consulted the database")
		return nil
	}, time.Second, slog.New(slog.DiscardHandler))
	for _, path := range []string{"/healthz", "/readyz"} {
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest(http.MethodPost, path, nil))
		checkResponse(t, response, http.StatusMethodNotAllowed, "{\"status\":\"method_not_allowed\"}\n")
		if got := response.Header().Get("Allow"); got != http.MethodGet {
			t.Errorf("Allow = %q, want GET", got)
		}
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/parking", nil))
	checkResponse(t, response, http.StatusNotFound, "{\"status\":\"not_found\"}\n")
}

func checkResponse(t *testing.T, response *httptest.ResponseRecorder, status int, body string) {
	t.Helper()
	if response.Code != status || response.Body.String() != body {
		t.Fatalf("got HTTP %d %q, want HTTP %d %q", response.Code, response.Body.String(), status, body)
	}
	if got := response.Header().Get("Content-Type"); got != "application/json" {
		t.Errorf("Content-Type = %q, want application/json", got)
	}
	if got := response.Header().Get("Cache-Control"); got != "no-store" {
		t.Errorf("Cache-Control = %q, want no-store", got)
	}
}
