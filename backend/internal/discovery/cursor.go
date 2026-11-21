package discovery

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"strings"
	"time"
)

type cursor struct {
	Scope     string     `json:"scope"`
	ReleaseID string     `json:"release_id"`
	BBox      [4]float64 `json:"bbox"`
	After     string     `json:"after"`
	Expires   int64      `json:"expires"`
}

func (h *handler) cursorMAC(payload string) []byte {
	mac := hmac.New(sha256.New, h.cursorKey[:])
	_, _ = mac.Write([]byte(payload))
	return mac.Sum(nil)
}

func (h *handler) issueCursor(c cursor) string {
	body, _ := json.Marshal(c) // The validated fields are JSON-serializable.
	payload := base64.RawURLEncoding.EncodeToString(body)
	return payload + "." + base64.RawURLEncoding.EncodeToString(h.cursorMAC(payload))
}

func (h *handler) readCursor(token string, q *query, now time.Time) (cursor, string) {
	var c cursor
	if !h.synthetic || len(token) > 1024 {
		return c, "INVALID_CURSOR"
	}
	payload, encodedMAC, ok := strings.Cut(token, ".")
	mac, err := base64.RawURLEncoding.Strict().DecodeString(encodedMAC)
	if !ok || err != nil || !hmac.Equal(mac, h.cursorMAC(payload)) {
		return c, "INVALID_CURSOR"
	}
	body, err := base64.RawURLEncoding.Strict().DecodeString(payload)
	if err != nil || json.Unmarshal(body, &c) != nil || !idPattern.MatchString(c.ReleaseID) ||
		!idPattern.MatchString(c.After) || c.Expires <= now.Unix() {
		return c, "INVALID_CURSOR"
	}
	if c.Scope != q.scope || c.BBox != [4]float64(q.bbox) || (q.pin != "" && c.ReleaseID != q.pin) {
		return c, "RELEASE_CONTEXT_MISMATCH"
	}
	q.pin, q.after = c.ReleaseID, c.After
	return c, ""
}
