package discovery

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestRequestValidation(t *testing.T) {
	bbox := "&bbox=0,0,0.1,0.1"
	for _, tc := range []struct{ path, code string }{
		{currentPath, "INVALID_SCOPE"},
		{currentPath + "?scope=bad%20scope", "INVALID_SCOPE"},
		{currentPath + "?scope=a&scope=b", "INVALID_QUERY"},
		{currentPath + "?scope=a&release_id=" + uid(1), "INVALID_QUERY"},
		{mapPath + "?scope=a&bbox=0,0,Infinity,0.1", "INVALID_BBOX"},
		{mapPath + "?scope=a&bbox=0,0,0.1,NaN", "INVALID_BBOX"},
		{mapPath + "?scope=a&bbox=180,0,180.1,0.1", "INVALID_BBOX"},
		{mapPath + "?scope=a&bbox=0,-90.1,0.1,-90", "INVALID_BBOX"},
		{mapPath + "?scope=a&bbox=179,0,-179,0.1", "INVALID_BBOX"},
		{mapPath + "?scope=a&bbox=0,0.1,0.1,0.05", "INVALID_BBOX"},
		{mapPath + "?scope=a&bbox=0,0,0.5,0.1", "VIEWPORT_TOO_LARGE"},
		{mapPath + "?scope=a&bbox=0,0,0.1,0.5", "VIEWPORT_TOO_LARGE"},
		{mapPath + "?scope=a" + bbox + "&limit=251", "INVALID_LIMIT"},
		{mapPath + "?scope=a" + bbox + "&limit=0", "INVALID_LIMIT"},
		{mapPath + "?scope=a" + bbox + "&limit=1.0", "INVALID_LIMIT"},
		{mapPath + "?scope=a" + bbox + "&release_id=", "INVALID_RELEASE_ID"},
		{mapPath + "?scope=a" + bbox + "&cursor=forged", "INVALID_CURSOR"},
		{zonePrefix + uid(1) + "?scope=a", "RELEASE_PIN_REQUIRED"},
		{zonePrefix + "invalid?scope=a&release_id=" + uid(1), "INVALID_SOURCE_ZONE_ID"},
	} {
		t.Run(tc.code+"/"+tc.path, func(t *testing.T) {
			rec := httptest.NewRecorder()
			NewHandler(nil, time.Second).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, tc.path, nil))
			assertError(t, response{rec.Code, rec.Header(), rec.Body.Bytes()}, 400, tc.code)
		})
	}
	rec := httptest.NewRecorder()
	NewHandler(nil, time.Second).ServeHTTP(rec, httptest.NewRequest(http.MethodPost, mapPath, nil))
	assertError(t, response{rec.Code, rec.Header(), rec.Body.Bytes()}, 405, "METHOD_NOT_ALLOWED")
	if rec.Header().Get("Allow") != http.MethodGet {
		t.Fatal("expected Allow: GET")
	}
}

func TestCursorExpiryAndBinding(t *testing.T) {
	h := handler{synthetic: true, cursorKey: [32]byte{3}}
	now := time.Unix(10000, 0)
	c := cursor{Scope: "scope", ReleaseID: uid(1), BBox: [4]float64{0, 0, 0.1, 0.1}, After: uid(2), Expires: now.Add(time.Minute).Unix()}
	token := h.issueCursor(c)
	q := query{scope: c.Scope, bbox: c.BBox[:]}
	if got, code := h.readCursor(token, &q, now); code != "" || got != c || q.pin != c.ReleaseID || q.after != c.After {
		t.Fatalf("cursor did not pin release: %#v %s", got, code)
	}
	for _, tc := range []struct {
		name string
		q    query
		now  time.Time
		h    handler
		code string
	}{
		{"expired", q, now.Add(time.Minute), h, "INVALID_CURSOR"},
		{"different process key", q, now, handler{synthetic: true}, "INVALID_CURSOR"},
		{"release", query{scope: c.Scope, bbox: c.BBox[:], pin: uid(9)}, now, h, "RELEASE_CONTEXT_MISMATCH"},
		{"scope", query{scope: "other", bbox: c.BBox[:]}, now, h, "RELEASE_CONTEXT_MISMATCH"},
		{"bounding box", query{scope: c.Scope, bbox: []float64{0, 0, 0.1, 0.2}}, now, h, "RELEASE_CONTEXT_MISMATCH"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if _, code := tc.h.readCursor(token, &tc.q, tc.now); code != tc.code {
				t.Fatalf("got %s want %s", code, tc.code)
			}
		})
	}
}

func assertError(t *testing.T, got response, status int, code string) {
	t.Helper()
	if got.status != status || got.header.Get("Content-Type") != "application/json" {
		t.Fatalf("want JSON %d %s, got %d %s", status, code, got.status, got.body)
	}
	body := decode[struct {
		Error apiError `json:"error"`
	}](t, got)
	if body.Error.Code != code || body.Error.RequestID == "" || body.Error.Message == "" || body.Error.Retryable != (status == 503) ||
		got.header.Get("Cache-Control") != "no-store" {
		t.Fatalf("unexpected error envelope: %s", got.body)
	}
}
