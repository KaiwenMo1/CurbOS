// Command api runs the CurbOS operational HTTP server.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/KaiwenMo1/CurbOS/backend/internal/platform/postgres"
	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stderr, nil))
	cfg, err := loadConfig(os.Getenv)
	if err != nil {
		logger.Error("configuration rejected", "error", err)
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	err = run(ctx, cfg, logger)
	stop()
	if err != nil {
		logger.Error("API stopped with error", "error", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, cfg config, logger *slog.Logger) error {
	listener, err := net.Listen("tcp", cfg.listenAddr)
	if err != nil {
		return fmt.Errorf("listen for HTTP: %w", err)
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg.database)
	if err != nil {
		_ = listener.Close()
		return errors.New("initialize PostgreSQL pool")
	}
	return serveAPI(ctx, listener, cfg, pool, logger)
}

// serveAPI owns the listener and pool from entry until shutdown completes.
func serveAPI(ctx context.Context, listener net.Listener, cfg config, pool *pgxpool.Pool, logger *slog.Logger) error {
	requestCtx, cancelRequests := context.WithCancel(context.Background())
	defer cancelRequests()
	server := &http.Server{
		Handler: newHandler(func(ctx context.Context) error {
			return postgres.CheckReady(ctx, pool)
		}, cfg.readinessTimeout, logger),
		BaseContext:       func(net.Listener) context.Context { return requestCtx },
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       time.Minute,
		ErrorLog:          slog.NewLogLogger(logger.Handler(), slog.LevelError),
	}
	served := make(chan error, 1)
	go func() { served <- server.Serve(listener) }()
	logger.Info("API started", "listen_addr", listener.Addr().String())

	var serveErr error
	select {
	case err := <-served:
		if !errors.Is(err, http.ErrServerClosed) {
			serveErr = fmt.Errorf("serve HTTP: %w", err)
		}
	case <-ctx.Done():
	}

	logger.Info("API shutdown started")
	shutdownContext, cancel := context.WithTimeout(context.Background(), cfg.shutdownTimeout)
	defer cancel()
	var shutdownErr error
	if err := server.Shutdown(shutdownContext); err != nil {
		cancelRequests()
		_ = server.Close()
		shutdownErr = fmt.Errorf("graceful HTTP shutdown: %w", err)
	}
	cancelRequests()

	// pgxpool.Close has no context and waits for checked-out connections.
	poolClosed := make(chan struct{})
	go func() {
		pool.Close()
		close(poolClosed)
	}()
	select {
	case <-poolClosed:
		logger.Info("API stopped")
		return errors.Join(serveErr, shutdownErr)
	case <-shutdownContext.Done():
		return errors.Join(serveErr, shutdownErr, fmt.Errorf("close PostgreSQL pool: %w", shutdownContext.Err()))
	}
}
