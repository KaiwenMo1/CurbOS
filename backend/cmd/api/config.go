package main

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type config struct {
	listenAddr       string
	readinessTimeout time.Duration
	discoveryTimeout time.Duration
	shutdownTimeout  time.Duration
	database         *pgxpool.Config
}

func loadConfig(getenv func(string) string) (config, error) {
	addr := getenv("CURBOS_HTTP_ADDR")
	if addr == "" {
		addr = "127.0.0.1:8080"
	}
	host, port, err := net.SplitHostPort(addr)
	portNumber, portErr := strconv.ParseUint(port, 10, 16)
	if err != nil || portErr != nil || portNumber == 0 || (host != "" && host != "localhost" && net.ParseIP(host) == nil) {
		return config{}, errors.New("CURBOS_HTTP_ADDR must be a listen address with a port from 1 to 65535")
	}

	ready, err := readDuration(getenv, "CURBOS_READY_TIMEOUT", time.Second, 5*time.Second)
	if err != nil {
		return config{}, err
	}
	discovery, err := readDuration(getenv, "CURBOS_DISCOVERY_TIMEOUT", 2*time.Second, 5*time.Second)
	if err != nil {
		return config{}, err
	}
	shutdown, err := readDuration(getenv, "CURBOS_SHUTDOWN_TIMEOUT", 10*time.Second, 30*time.Second)
	if err != nil {
		return config{}, err
	}
	database, err := parseDatabaseConfig(getenv("CURBOS_DATABASE_URL"))
	if err != nil {
		return config{}, err
	}
	return config{listenAddr: addr, readinessTimeout: ready, discoveryTimeout: discovery, shutdownTimeout: shutdown, database: database}, nil
}

func readDuration(getenv func(string) string, key string, fallback, max time.Duration) (time.Duration, error) {
	raw := getenv(key)
	if raw == "" {
		return fallback, nil
	}
	duration, err := time.ParseDuration(raw)
	if err != nil || duration < time.Millisecond || duration > max {
		return 0, fmt.Errorf("%s must be a duration between 1ms and %s", key, max)
	}
	return duration, nil
}

func parseDatabaseConfig(raw string) (*pgxpool.Config, error) {
	dsn, err := url.Parse(raw)
	if err != nil || (dsn.Scheme != "postgres" && dsn.Scheme != "postgresql") ||
		dsn.Hostname() == "" || dsn.User == nil || dsn.User.Username() == "" || len(dsn.Path) < 2 || dsn.Fragment != "" {
		return nil, errors.New("CURBOS_DATABASE_URL must be a PostgreSQL URL with a host, user and database")
	}
	query, err := url.ParseQuery(dsn.RawQuery)
	if err != nil {
		return nil, errors.New("CURBOS_DATABASE_URL has invalid query parameters")
	}
	host := dsn.Hostname()
	port := dsn.Port()
	if port == "" {
		port = "5432"
	}
	portNumber, err := strconv.ParseUint(port, 10, 16)
	if err != nil || portNumber == 0 {
		return nil, errors.New("CURBOS_DATABASE_URL port must be from 1 to 65535")
	}
	dsn.Host = net.JoinHostPort(host, port)
	if password, specified := dsn.User.Password(); (specified && password == "") ||
		(query.Has("password") && query.Get("password") == "") {
		return nil, errors.New("CURBOS_DATABASE_URL must omit the password or supply a non-empty value")
	}
	loopback := host == "localhost" || net.ParseIP(host).IsLoopback()
	switch mode := query.Get("sslmode"); mode {
	case "":
		query.Set("sslmode", "verify-full")
	case "verify-full", "verify-ca", "require":
	case "disable":
		if !loopback {
			return nil, errors.New("CURBOS_DATABASE_URL may disable TLS only for a loopback host")
		}
	default:
		return nil, errors.New("CURBOS_DATABASE_URL sslmode must be verify-full, verify-ca, require or disable")
	}
	dsn.RawQuery = query.Encode()

	cfg, err := pgxpool.ParseConfig(dsn.String())
	if err != nil {
		// pgx parse errors can contain the original URL and connection options.
		return nil, errors.New("CURBOS_DATABASE_URL has invalid PostgreSQL connection settings")
	}
	conn := cfg.ConnConfig
	if conn.Host != host || conn.Port != uint16(portNumber) || conn.User != dsn.User.Username() ||
		conn.Database != strings.TrimPrefix(dsn.Path, "/") ||
		len(conn.Fallbacks) != 0 || (!loopback && conn.TLSConfig == nil) {
		return nil, errors.New("CURBOS_DATABASE_URL must identify one database target without connection overrides")
	}
	conn.ConnectTimeout = 5 * time.Second
	cfg.MinConns = 0
	cfg.MinIdleConns = 0
	cfg.MaxConns = 4
	return cfg, nil
}
