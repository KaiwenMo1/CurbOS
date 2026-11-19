package main

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// The integration harness calls this with its disposable, migrated database.
func testShutdownWithActiveProbe(t *testing.T, cfg config, force bool) {
	cfg.readinessTimeout = 5 * time.Second
	cfg.shutdownTimeout = 2 * time.Second
	if force {
		cfg.shutdownTimeout = 150 * time.Millisecond
	}
	testCtx, stopTest := context.WithTimeout(t.Context(), 12*time.Second)
	defer stopTest()
	ctx, cancelServer := context.WithCancel(context.Background())
	defer cancelServer()
	pool, err := pgxpool.NewWithConfig(testCtx, cfg.database)
	if err != nil {
		t.Fatal("initialize shutdown test pool")
	}
	// Failures before serveAPI takes ownership still need to close the pool.
	defer pool.Close()
	tx, err := pool.Begin(testCtx)
	if err != nil {
		t.Fatal("begin shutdown test transaction")
	}
	releaseLock := func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = tx.Rollback(ctx)
	}
	defer releaseLock()
	if _, err := tx.Exec(testCtx, "LOCK TABLE public.goose_db_version IN ACCESS EXCLUSIVE MODE"); err != nil {
		t.Fatal("lock migration history in the isolated database")
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- serveAPI(ctx, listener, cfg, pool, slog.New(slog.DiscardHandler)) }()

	client := &http.Client{Timeout: 6 * time.Second}
	defer client.CloseIdleConnections()
	type result struct {
		status int
		err    error
	}
	response := make(chan result, 1)
	go func() {
		res, err := client.Get("http://" + listener.Addr().String() + "/readyz")
		if err != nil {
			response <- result{err: err}
			return
		}
		defer res.Body.Close()
		_, err = io.Copy(io.Discard, res.Body)
		response <- result{status: res.StatusCode, err: err}
	}()

	// Wait until PostgreSQL confirms that the HTTP probe is executing and blocked.
	for {
		var waiting bool
		err := pool.QueryRow(testCtx, `
			SELECT EXISTS (
				SELECT 1 FROM pg_catalog.pg_stat_activity
				WHERE datname = current_database() AND wait_event_type = 'Lock'
				AND query LIKE '%SELECT public.postgis_lib_version()%'
			)`).Scan(&waiting)
		if err != nil {
			t.Fatal("observe blocked readiness query")
		}
		if waiting {
			break
		}
		select {
		case early := <-response:
			t.Fatalf("readiness request finished before the shutdown test: %+v", early)
		case <-time.After(20 * time.Millisecond):
		}
	}

	cancelServer()
	if !force {
		// A refused new connection confirms shutdown has begun while the probe is blocked.
		for {
			conn, err := (&net.Dialer{Timeout: 50 * time.Millisecond}).DialContext(testCtx, "tcp", listener.Addr().String())
			if err != nil {
				break
			}
			_ = conn.Close()
			time.Sleep(10 * time.Millisecond)
		}
		releaseLock()
	}
	select {
	case err := <-done:
		if force && !errors.Is(err, context.DeadlineExceeded) {
			t.Errorf("forced shutdown error = %v, want deadline exceeded", err)
		}
		if !force && err != nil {
			t.Errorf("graceful shutdown: %v", err)
		}
	case <-time.After(cfg.shutdownTimeout + time.Second):
		t.Fatal("API shutdown exceeded its budget while a connection remained checked out")
	}
	select {
	case res := <-response:
		if force && res.err == nil {
			t.Errorf("forced shutdown left an HTTP response: %+v", res)
		}
		if !force && (res.err != nil || res.status != http.StatusOK) {
			t.Errorf("in-flight readiness check did not complete: %+v", res)
		}
	case <-time.After(time.Second):
		t.Fatal("in-flight readiness request did not exit")
	}
}
