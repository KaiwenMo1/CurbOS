package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"
)

func newHandler(checkReady func(context.Context) error, readinessTimeout time.Duration, logger *slog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/healthz", "/readyz":
		default:
			writeStatus(w, http.StatusNotFound, "not_found")
			return
		}
		if r.Method != http.MethodGet {
			w.Header().Set("Allow", http.MethodGet)
			writeStatus(w, http.StatusMethodNotAllowed, "method_not_allowed")
			return
		}
		if r.URL.Path == "/healthz" {
			writeStatus(w, http.StatusOK, "ok")
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), readinessTimeout)
		defer cancel()
		err := checkReady(ctx)
		if err != nil || ctx.Err() != nil {
			reason := "database_unavailable"
			switch {
			case errors.Is(ctx.Err(), context.DeadlineExceeded), errors.Is(err, context.DeadlineExceeded):
				reason = "timeout"
			case errors.Is(ctx.Err(), context.Canceled), errors.Is(err, context.Canceled):
				reason = "canceled"
			}
			logger.Warn("readiness check failed", "reason", reason)
			writeStatus(w, http.StatusServiceUnavailable, "not_ready")
			return
		}
		writeStatus(w, http.StatusOK, "ready")
	})
}

type statusResponse struct {
	Status string `json:"status"`
}

func writeStatus(w http.ResponseWriter, code int, status string) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(statusResponse{Status: status})
}
