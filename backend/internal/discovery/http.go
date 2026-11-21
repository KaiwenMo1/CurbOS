// Package discovery serves release-pinned, evidence-aware curb reads.
package discovery

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	currentPath = "/v1/parking/releases/current"
	mapPath     = "/v1/parking/map"
	zonePrefix  = "/v1/parking/zones/"
	maxSpan     = 0.25
	maxLimit    = 250
)

var (
	scopePattern  = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,100}$`)
	idPattern     = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	numberPattern = regexp.MustCompile(`^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$`)
)

type query struct {
	scope  string
	pin    string
	bbox   []float64
	limit  int
	zone   string
	after  string
	cursor string
}

type handler struct {
	pool      *pgxpool.Pool
	timeout   time.Duration
	synthetic bool
	cursorKey [32]byte
}

// NewHandler is the normal API entry point. Synthetic visibility is only
// constructed by tests, which also must use the separate database capability.
func NewHandler(pool *pgxpool.Pool, timeout time.Duration) http.Handler {
	return &handler{pool: pool, timeout: timeout}
}

func (h *handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	path := r.URL.Path
	if path != currentPath && path != mapPath && !strings.HasPrefix(path, zonePrefix) {
		fail(w, http.StatusNotFound, "ENDPOINT_NOT_FOUND", "Endpoint not found.")
		return
	}
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", http.MethodGet)
		fail(w, http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED", "Use GET.")
		return
	}
	q, issue := parseQuery(r)
	if issue != "" {
		fail(w, http.StatusBadRequest, issue, "Check the request parameters.")
		return
	}
	var token cursor
	if q.cursor != "" {
		var code string
		token, code = h.readCursor(q.cursor, &q, time.Now())
		if code != "" {
			status := http.StatusBadRequest
			if code == "RELEASE_CONTEXT_MISMATCH" {
				status = http.StatusConflict
			}
			fail(w, status, code, "Use a fresh cursor for the same release and viewport.")
			return
		}
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.timeout)
	defer cancel()
	data, err := read(ctx, h.pool, q, h.synthetic)
	if err != nil || ctx.Err() != nil {
		fail(w, http.StatusServiceUnavailable, "DISCOVERY_UNAVAILABLE", "Parking evidence is temporarily unavailable.")
		return
	}
	switch data.ErrorCode {
	case "":
	case "RELEASE_WITHDRAWN":
		fail(w, http.StatusGone, data.ErrorCode, "The selected release was withdrawn.")
		return
	case "RELEASE_NOT_FOUND", "SCOPE_UNKNOWN", "FEATURE_NOT_PUBLISHED":
		fail(w, http.StatusNotFound, data.ErrorCode, "The requested evidence is unavailable.")
		return
	default:
		fail(w, http.StatusServiceUnavailable, "DISCOVERY_UNAVAILABLE", "Parking evidence is temporarily unavailable.")
		return
	}

	switch path {
	case currentPath:
		writeJSON(w, "application/json", http.StatusOK, data.release)
	case mapPath:
		h.writeMap(w, q, data, token)
	default:
		detail := zoneDetail{release: data.release, Feature: data.Feature, PolicyRefs: data.PolicyRefs}
		writeJSON(w, "application/json", http.StatusOK, detail)
	}
}

func parseQuery(r *http.Request) (query, string) {
	var q query
	if len(r.URL.RawQuery) > 4096 {
		return q, "INVALID_QUERY"
	}
	v, err := url.ParseQuery(r.URL.RawQuery)
	if err != nil {
		return q, "INVALID_QUERY"
	}
	isMap := r.URL.Path == mapPath
	isDetail := strings.HasPrefix(r.URL.Path, zonePrefix)
	for key, values := range v {
		allowed := key == "scope" || (key == "release_id" && (isMap || isDetail)) ||
			(isMap && (key == "bbox" || key == "limit" || key == "cursor"))
		if !allowed || len(values) != 1 {
			return q, "INVALID_QUERY"
		}
	}
	q.scope = v.Get("scope")
	if !scopePattern.MatchString(q.scope) {
		return q, "INVALID_SCOPE"
	}
	q.pin = v.Get("release_id")
	if v.Has("release_id") && !idPattern.MatchString(q.pin) {
		return q, "INVALID_RELEASE_ID"
	}
	if isDetail {
		q.zone = strings.TrimPrefix(r.URL.Path, zonePrefix)
		if !idPattern.MatchString(q.zone) {
			return q, "INVALID_SOURCE_ZONE_ID"
		}
		if q.pin == "" {
			return q, "RELEASE_PIN_REQUIRED"
		}
	}
	if !isMap {
		return q, ""
	}
	q.bbox, err = parseBBox(v.Get("bbox"))
	if err != nil {
		return q, "INVALID_BBOX"
	}
	if q.bbox[2]-q.bbox[0] > maxSpan || q.bbox[3]-q.bbox[1] > maxSpan {
		return q, "VIEWPORT_TOO_LARGE"
	}
	q.cursor = v.Get("cursor")
	if v.Has("cursor") && q.cursor == "" {
		return q, "INVALID_CURSOR"
	}
	q.limit = 100
	if v.Has("limit") {
		val := v.Get("limit")
		n, err := strconv.ParseUint(val, 10, 16)
		if err != nil || n < 1 || n > maxLimit {
			return q, "INVALID_LIMIT"
		}
		q.limit = int(n)
	}
	return q, ""
}

func parseBBox(raw string) ([]float64, error) {
	parts := strings.Split(raw, ",")
	if len(parts) != 4 {
		return nil, strconv.ErrSyntax
	}
	bounds := make([]float64, 4)
	for i, part := range parts {
		if !numberPattern.MatchString(part) {
			return nil, strconv.ErrSyntax
		}
		n, err := strconv.ParseFloat(part, 64)
		maximum := float64(180 - (i%2)*90)
		if err != nil || n < -maximum || n > maximum {
			return nil, strconv.ErrRange
		}
		bounds[i] = n
	}
	if bounds[0] >= bounds[2] || bounds[1] >= bounds[3] {
		return nil, strconv.ErrRange
	}
	return bounds, nil
}

func (h *handler) writeMap(w http.ResponseWriter, q query, data result, previous cursor) {
	if data.Features == nil {
		data.Features = []zoneFeature{}
	}
	m := mapResponse{
		Type: "FeatureCollection", Features: data.Features,
		Meta: mapMeta{release: data.release, Coverage: data.Coverage, Request: "COMPLETE",
			Exclusions: []exclusion{{Reason: "VIEWPORT_EXCLUSIONS", CountStatus: "NOT_COMPUTED"}}},
	}
	if len(m.Features) > q.limit {
		m.Features = m.Features[:q.limit]
		expires := previous.Expires
		if expires == 0 {
			expires = time.Now().Add(15 * time.Minute).Unix()
		}
		next := h.issueCursor(cursor{Scope: q.scope, ReleaseID: *data.ReleaseID,
			BBox: [4]float64(q.bbox), After: m.Features[len(m.Features)-1].ID, Expires: expires})
		m.Links.NextCursor = &next
	}
	writeJSON(w, "application/geo+json", http.StatusOK, m)
}

type apiError struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	RequestID string `json:"request_id"`
	Retryable bool   `json:"retryable"`
}

func fail(w http.ResponseWriter, status int, code, message string) {
	body := struct {
		Error apiError `json:"error"`
	}{apiError{Code: code, Message: message, RequestID: rand.Text(), Retryable: status == http.StatusServiceUnavailable}}
	writeJSON(w, "application/json", status, body)
}

func writeJSON(w http.ResponseWriter, contentType string, status int, body any) {
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
