package main

import (
	"strings"
	"testing"
	"time"
)

func TestConfigDefaultsAndOverrides(t *testing.T) {
	t.Setenv("PGPORT", "6432")
	env := map[string]string{"CURBOS_DATABASE_URL": "postgres://curbos@127.0.0.1/curbos?sslmode=disable"}
	getenv := func(key string) string { return env[key] }
	cfg, err := loadConfig(getenv)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.listenAddr != "127.0.0.1:8080" || cfg.readinessTimeout != time.Second || cfg.discoveryTimeout != 2*time.Second || cfg.shutdownTimeout != 10*time.Second {
		t.Fatal("unexpected default listen address or timeout")
	}
	if cfg.database.ConnConfig.Port != 5432 || cfg.database.MaxConns != 4 || cfg.database.MinConns != 0 {
		t.Fatal("database port or pool limits did not match their defaults")
	}

	env["CURBOS_HTTP_ADDR"] = "[::]:8181"
	env["CURBOS_READY_TIMEOUT"] = "250ms"
	env["CURBOS_DISCOVERY_TIMEOUT"] = "4s"
	env["CURBOS_SHUTDOWN_TIMEOUT"] = "3s"
	env["CURBOS_DATABASE_URL"] = "postgres://curbos@db.example.test/curbos"
	cfg, err = loadConfig(getenv)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.listenAddr != "[::]:8181" || cfg.readinessTimeout != 250*time.Millisecond || cfg.discoveryTimeout != 4*time.Second || cfg.shutdownTimeout != 3*time.Second {
		t.Fatal("environment overrides were not applied")
	}
	tlsConfig := cfg.database.ConnConfig.TLSConfig
	if tlsConfig == nil || tlsConfig.InsecureSkipVerify || tlsConfig.ServerName != "db.example.test" {
		t.Fatal("remote database did not default to verified TLS")
	}
}

func TestConfigRejectsInvalidValuesWithoutDisclosingThem(t *testing.T) {
	const sensitive = "synthetic-private-config"
	for _, tc := range []struct{ key, value string }{
		{"CURBOS_DATABASE_URL", ""},
		{"CURBOS_DATABASE_URL", "postgres://" + sensitive + "@localhost:wrong/curbos"},
		{"CURBOS_DATABASE_URL", "postgres://curbos@" + sensitive + "/curbos?sslmode=disable"},
		{"CURBOS_DATABASE_URL", "postgres://curbos@localhost"},
		{"CURBOS_DATABASE_URL", "postgres://localhost/curbos"},
		{"CURBOS_DATABASE_URL", "postgres://curbos:@localhost/curbos"},
		{"CURBOS_DATABASE_URL", "postgres://curbos@localhost/curbos?password="},
		{"CURBOS_DATABASE_URL", "postgres://curbos@localhost:0/curbos"},
		{"CURBOS_DATABASE_URL", "postgres://curbos@localhost:5432/curbos?port=6432"},
		{"CURBOS_HTTP_ADDR", "127.0.0.1:0"},
		{"CURBOS_READY_TIMEOUT", "6s"},
		{"CURBOS_DISCOVERY_TIMEOUT", "6s"},
		{"CURBOS_SHUTDOWN_TIMEOUT", sensitive},
	} {
		t.Run(tc.key+"/"+tc.value, func(t *testing.T) {
			env := map[string]string{"CURBOS_DATABASE_URL": "postgres://curbos@127.0.0.1/curbos?sslmode=disable"}
			env[tc.key] = tc.value
			_, err := loadConfig(func(key string) string { return env[key] })
			if err == nil || !strings.Contains(err.Error(), tc.key) || strings.Contains(err.Error(), sensitive) {
				t.Fatal("expected a sanitized validation error identifying the environment variable")
			}
		})
	}
}
