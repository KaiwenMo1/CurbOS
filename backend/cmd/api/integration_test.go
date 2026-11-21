package main

import (
	"context"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestAPIIntegration(t *testing.T) {
	if os.Getenv("CURBOS_API_INTEGRATION") != "1" {
		t.Skip("run make api-test to provision a disposable PostgreSQL database")
	}
	project := os.Getenv("COMPOSE_PROJECT_NAME")
	container := os.Getenv("CURBOS_TEST_DB_CONTAINER")
	if !regexp.MustCompile(`^curbos-db-test-[0-9a-f]{16}$`).MatchString(project) ||
		!regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(container) {
		t.Fatal("integration test requires an isolated Compose test container")
	}
	cfg, err := loadConfig(os.Getenv)
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.CommandContext(t.Context(), "docker", "inspect", "--format",
		`{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}} {{range index .NetworkSettings.Ports "5432/tcp"}}{{.HostIp}}:{{.HostPort}}{{end}}`, container)
	identity, err := cmd.Output()
	conn := cfg.database.ConnConfig
	endpoint := net.JoinHostPort(conn.Host, strconv.Itoa(int(conn.Port)))
	if err != nil || conn.Host != "127.0.0.1" || conn.Database != "curbos" || conn.User != "curbos" ||
		strings.TrimSpace(string(identity)) != project+"/db "+endpoint {
		t.Fatal("database URL does not match the isolated Compose test container")
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = listener.Close() })
	ctx, cancel := context.WithCancel(t.Context())
	t.Cleanup(cancel)
	pool, err := pgxpool.NewWithConfig(ctx, cfg.database)
	if err != nil {
		t.Fatal("initialize integration pool")
	}
	done := make(chan error, 1)
	go func() { done <- serveAPI(ctx, listener, cfg, pool, slog.New(slog.DiscardHandler)) }()
	stopped := false
	stopServer := func() {
		cancel()
		select {
		case err := <-done:
			stopped = true
			if err != nil {
				t.Errorf("API shutdown: %v", err)
			}
		case <-time.After(8 * time.Second):
			t.Error("API did not stop")
		}
	}
	t.Cleanup(func() {
		if !stopped {
			stopServer()
		}
	})

	base := "http://" + listener.Addr().String()
	client := &http.Client{Timeout: 4 * time.Second}
	t.Cleanup(client.CloseIdleConnections)
	request := func(path string) (int, string) {
		t.Helper()
		response, err := client.Get(base + path)
		if err != nil {
			t.Fatalf("GET %s: %v", path, err)
		}
		defer response.Body.Close()
		body, err := io.ReadAll(response.Body)
		if err != nil {
			t.Fatal(err)
		}
		return response.StatusCode, string(body)
	}
	expect := func(path string, status int, body string) {
		t.Helper()
		gotStatus, gotBody := request(path)
		if gotStatus != status || gotBody != body {
			t.Fatalf("GET %s = %d %q, want %d %q", path, gotStatus, gotBody, status, body)
		}
	}

	expect("/healthz", 200, "{\"status\":\"ok\"}\n")
	head, err := client.Head(base + "/healthz")
	if err != nil {
		t.Fatal("request HEAD /healthz")
	}
	headBody, err := io.ReadAll(head.Body)
	_ = head.Body.Close()
	if err != nil || head.StatusCode != http.StatusMethodNotAllowed || head.Header.Get("Allow") != http.MethodGet || len(headBody) != 0 {
		t.Fatal("HEAD /healthz must return 405 with Allow: GET and no body")
	}
	expect("/readyz", 503, "{\"status\":\"not_ready\"}\n")
	migrationCtx, stopMigration := context.WithTimeout(t.Context(), time.Minute)
	defer stopMigration()
	migrate := exec.CommandContext(migrationCtx, "bash", "db/goose.sh", "up")
	migrate.Dir = "../../.."
	if output, err := migrate.CombinedOutput(); err != nil {
		t.Fatalf("migrate isolated database: %v\n%s", err, output)
	}
	expect("/readyz", 200, "{\"status\":\"ready\"}\n")
	if code, body := request("/v1/parking/releases/current?scope=synthetic-missing"); code != 404 || !strings.Contains(body, "SCOPE_UNKNOWN") {
		t.Fatalf("normal API did not route the Discovery request: %d %q", code, body)
	}

	control := func(action string) error {
		controlCtx, stopControl := context.WithTimeout(context.Background(), 10*time.Second)
		defer stopControl()
		return exec.CommandContext(controlCtx, "docker", action, container).Run()
	}
	if err := control("pause"); err != nil {
		t.Fatalf("pause isolated database: %v", err)
	}
	paused := true
	t.Cleanup(func() {
		if paused {
			if err := control("unpause"); err != nil {
				t.Errorf("unpause isolated database during cleanup: %v", err)
			}
		}
	})
	expect("/readyz", 503, "{\"status\":\"not_ready\"}\n")
	expect("/healthz", 200, "{\"status\":\"ok\"}\n")
	if err := control("unpause"); err != nil {
		t.Fatalf("unpause isolated database: %v", err)
	}
	paused = false
	deadline := time.Now().Add(10 * time.Second)
	for {
		status, body := request("/readyz")
		if status == 200 && body == "{\"status\":\"ready\"}\n" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("readiness did not recover: %d %q", status, body)
		}
		time.Sleep(100 * time.Millisecond)
	}

	stopServer()
	client.CloseIdleConnections()
	if response, err := client.Get(base + "/healthz"); err == nil {
		response.Body.Close()
		t.Error("API accepted a new HTTP connection after shutdown")
	}
	poolCtx, cancelPool := context.WithTimeout(t.Context(), time.Second)
	defer cancelPool()
	if conn, err := pool.Acquire(poolCtx); err == nil {
		conn.Release()
		t.Error("database pool accepted an acquisition after API shutdown")
	} else if poolCtx.Err() != nil {
		t.Error("closed pool did not reject acquisition immediately")
	}

	t.Run("drain active probe", func(t *testing.T) { testShutdownWithActiveProbe(t, cfg, false) })
	t.Run("force close active probe and bound pool cleanup", func(t *testing.T) { testShutdownWithActiveProbe(t, cfg, true) })
}
