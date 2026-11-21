package discovery

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/KaiwenMo1/CurbOS/backend/internal/platform/postgres"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

type response struct {
	status int
	header http.Header
	body   []byte
}

func request(ctx context.Context, client *http.Client, url string) (response, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return response{}, err
	}
	res, err := client.Do(req)
	if err != nil {
		return response{}, err
	}
	defer res.Body.Close()
	body, err := io.ReadAll(res.Body)
	return response{res.StatusCode, res.Header, body}, err
}

func get(t *testing.T, server *httptest.Server, path string) response {
	t.Helper()
	got, err := request(t.Context(), server.Client(), server.URL+path)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

func decode[T any](t *testing.T, got response) T {
	t.Helper()
	var body T
	if err := json.Unmarshal(got.body, &body); err != nil {
		t.Fatalf("invalid JSON: %s", got.body)
	}
	return body
}

func expectMap(t *testing.T, got response, state, coverage string, f fixture, version int64) mapResponse {
	t.Helper()
	if got.status != 200 || got.header.Get("Content-Type") != "application/geo+json" || got.header.Get("Cache-Control") != "no-store" {
		t.Fatalf("unexpected map status, headers or body: %#v", got)
	}
	body := decode[mapResponse](t, got)
	if body.Type != "FeatureCollection" || body.Features == nil || body.Meta.PublicationState != state ||
		body.Meta.Coverage != coverage || body.Meta.PointerVersion != version || body.Meta.PublicEligible ||
		len(body.Meta.Exclusions) != 1 || body.Meta.Exclusions[0].Count != nil ||
		body.Meta.Exclusions[0].CountStatus != "NOT_COMPUTED" {
		t.Fatalf("unexpected map contract: %s", got.body)
	}
	if f.releaseID == "" {
		if body.Meta.ReleaseID != nil || len(body.Features) != 0 || body.Meta.DataStatus == "SYNTHETIC_TEST_DATA" {
			t.Fatalf("hidden release leaked: %s", got.body)
		}
	} else {
		if body.Meta.ReleaseID == nil || *body.Meta.ReleaseID != f.releaseID || body.Meta.DataStatus != "SYNTHETIC_TEST_DATA" {
			t.Fatalf("release mismatch: %s", got.body)
		}
		for _, zone := range body.Features {
			expectEvidence(t, zone, f)
		}
	}
	assertSafe(t, got)
	return body
}

func expectEvidence(t *testing.T, zone zoneFeature, f fixture) {
	t.Helper()
	p := zone.Properties
	points := 2
	if zone.ID == uid(10) {
		points = 3
	}
	if zone.ID != p.SourceZoneID || zone.Type != "Feature" || zone.Geometry.Type != "LineString" ||
		len(zone.Geometry.Coordinates) != points || zone.Geometry.Coordinates[0][0] != f.longitude ||
		p.SourceArtifactID != f.artifactID || p.Publisher != "synthetic-test" || p.SourceAsOf == nil ||
		p.GeometryEvidence != "SOURCE_REPORTED" || p.CurbPlacement != "UNVERIFIED" || p.StreetSide == nil || *p.StreetSide != "LEFT" ||
		p.RoadReference == nil || *p.RoadReference != "fixture-road" || p.PolicyReferenceStatus != "RESOLVED_REFERENCES_ONLY" ||
		p.ParkingLegality != "UNKNOWN" || p.Occupancy != "UNKNOWN" || p.Availability != "UNKNOWN" {
		t.Fatalf("unexpected zone evidence: %+v", zone)
	}
}

func assertSafe(t *testing.T, got response) {
	t.Helper()
	for _, forbidden := range []string{
		"capacity", "num_spaces", "vacancy", "resource_id", "private-raw", "cas+sha256",
		"private-rights", "private operator", "verified_by", "fixture-policy-payload", "evidence_ref",
	} {
		if strings.Contains(string(got.body), forbidden) {
			t.Fatalf("response leaked %q", forbidden)
		}
	}
}

func TestDiscoveryIntegration(t *testing.T) {
	admin := disposablePool(t)
	registrar := testLogin(t, admin, "registrar", "curbos_publication_registrar")
	verifier := testLogin(t, admin, "verifier", "curbos_publication_verifier")
	reviewer := testLogin(t, admin, "reviewer", "curbos_publication_reviewer")
	operator := testLogin(t, admin, "operator", "curbos_publication_operator")
	api := testLogin(t, admin, "reader", "curbos_api_reader")
	reader := testLogin(t, admin, "synthetic", "curbos_api_synthetic_reader")

	a := seedFixture(t, admin, registrar, verifier, reviewer, 100, "synthetic-discovery-one", true)
	b := seedFixture(t, admin, registrar, verifier, reviewer, 200, a.scope, true)
	c := seedFixture(t, admin, registrar, verifier, reviewer, 300, "synthetic-discovery-other", true)
	pending := seedFixture(t, admin, registrar, verifier, reviewer, 400, a.scope, false)
	testHandler := &handler{pool: reader, timeout: 5 * time.Second, synthetic: true}
	rand.Read(testHandler.cursorKey[:])
	synthetic := httptest.NewServer(testHandler)
	t.Cleanup(synthetic.Close)
	normal := httptest.NewServer(NewHandler(api, time.Second))
	t.Cleanup(normal.Close)

	current := currentPath + "?scope=" + a.scope
	mapping := mapPath + "?scope=" + a.scope + "&bbox=0,0,0.1,0.1"
	detail := func(id, pin string) string { return zonePrefix + id + "?scope=" + a.scope + "&release_id=" + pin }

	t.Run("no active and unknown scope", func(t *testing.T) {
		got := get(t, synthetic, current)
		r := decode[release](t, got)
		if got.status != 200 || r.PublicationState != "NO_PUBLIC_RELEASE" || r.DataStatus != "NO_ACTIVE_RELEASE" ||
			r.PointerVersion != 0 || r.ReleaseID != nil {
			t.Fatalf("no active release response: %s", got.body)
		}
		expectMap(t, get(t, synthetic, mapping), "NO_PUBLIC_RELEASE", "NO_PUBLIC_RELEASE", fixture{}, 0)
		assertError(t, get(t, synthetic, currentPath+"?scope=synthetic-unknown"), 404, "SCOPE_UNKNOWN")
		assertError(t, get(t, synthetic, detail(uid(10), pending.releaseID)), 404, "RELEASE_NOT_FOUND")
		assertError(t, get(t, synthetic, detail(uid(10), b.releaseID)), 404, "RELEASE_NOT_FOUND")
	})

	change(t, operator, a.scope, &a.releaseID, 0, "ACTIVATE")
	change(t, operator, c.scope, &c.releaseID, 0, "ACTIVATE")
	t.Run("synthetic guard and read only login", func(t *testing.T) {
		expectMap(t, get(t, normal, mapping), "NO_PUBLIC_RELEASE", "NO_PUBLIC_RELEASE", fixture{}, 0)
		got := get(t, normal, current)
		r := decode[release](t, got)
		if got.status != 200 || r.PublicationState != "NO_PUBLIC_RELEASE" || r.PointerVersion != 0 ||
			r.ReleaseID != nil || r.PublicEligible {
			t.Fatalf("regular API disclosed synthetic pointer: %s", got.body)
		}
		assertError(t, get(t, normal, detail(uid(10), a.releaseID)), 404, "RELEASE_NOT_FOUND")
		if err := postgres.CheckReady(t.Context(), api); err != nil {
			t.Fatal("least privileged API reader cannot check readiness")
		}
		for _, statement := range []string{
			"SELECT discovery.read_synthetic('synthetic-discovery-one', NULL, NULL, NULL, 0, NULL)",
			"SELECT publication.register_candidate(NULL,NULL,NULL,NULL,NULL)",
			"SELECT publication.verify_candidate(NULL,NULL,NULL,NULL,NULL)",
			"SELECT publication.approve_release(NULL,NULL)",
			"SELECT publication.freeze_release(NULL)",
			"SELECT publication.change_pointer(NULL,NULL,NULL,NULL,NULL,NULL)",
			"INSERT INTO sources.activation_event DEFAULT VALUES",
			"UPDATE sources.active_release SET release_id = NULL",
			"UPDATE geo.release_curb_zone SET resource_id = NULL",
			"SELECT content_uri FROM sources.raw_artifact",
		} {
			_, err := api.Exec(t.Context(), statement)
			var sqlErr *pgconn.PgError
			if !errors.As(err, &sqlErr) || sqlErr.Code != "42501" {
				t.Fatalf("normal reader permission for %q: %v", statement, err)
			}
		}
	})

	var next string
	t.Run("viewport, pagination, and evidence", func(t *testing.T) {
		got := get(t, synthetic, current)
		active := decode[release](t, got)
		if got.status != 200 || active.ReleaseID == nil || *active.ReleaseID != a.releaseID ||
			active.PublicationState != "ACTIVE" || active.DataStatus != "SYNTHETIC_TEST_DATA" || !active.IsCurrent ||
			active.PointerVersion != 1 || active.PublicEligible || active.ActivatedAt == nil || active.SourceAsOf == nil || len(active.Attribution) != 1 {
			t.Fatalf("unexpected active release: %s", got.body)
		}
		m := expectMap(t, get(t, synthetic, mapping+"&limit=2"), "ACTIVE", "PARTIAL_SOURCE_COVERAGE", a, 1)
		if len(m.Features) != 2 || m.Features[0].ID != uid(10) || m.Features[1].ID != uid(20) || m.Links.NextCursor == nil ||
			len(m.Features[0].Properties.QACodes) != 1 || m.Features[0].Properties.QACodes[0] != "ZONE_GEOMETRY_REPEATED_VERTEX" {
			t.Fatalf("unexpected first page: %+v", m)
		}
		next = *m.Links.NextCursor
		empty := expectMap(t, get(t, synthetic, mapPath+"?scope="+a.scope+"&bbox=0.12,0.12,0.15,0.15"),
			"ACTIVE", "ASSESSED_NO_SOURCE_FEATURES", a, 1)
		if len(empty.Features) != 0 {
			t.Fatal("unrelated geometry appeared in viewport")
		}
		expectMap(t, get(t, synthetic, mapPath+"?scope="+a.scope+"&bbox=1,1,1.1,1.1"), "ACTIVE", "OUTSIDE_REVIEWED_SCOPE", a, 1)
		expectMap(t, get(t, synthetic, mapPath+"?scope="+a.scope+"&bbox=-0.05,0,0.005,0.01"), "ACTIVE", "PARTIAL_SOURCE_COVERAGE", a, 1)
		d := expectDetail(t, get(t, synthetic, detail(uid(10), a.releaseID)), a, 1)
		if !d.IsCurrent {
			t.Fatal("current-release detail was labeled historical")
		}
		assertError(t, get(t, synthetic, detail(uid(999), a.releaseID)), 404, "FEATURE_NOT_PUBLISHED")
		assertError(t, get(t, synthetic, detail(uid(10), c.releaseID)), 404, "RELEASE_NOT_FOUND")
		assertError(t, get(t, synthetic, mapping+"&cursor="+url.QueryEscape(next)+"&release_id="+c.releaseID), 409, "RELEASE_CONTEXT_MISMATCH")
		assertError(t, get(t, synthetic, mapPath+"?scope="+a.scope+"&bbox=0,0,0.2,0.2&cursor="+url.QueryEscape(next)), 409, "RELEASE_CONTEXT_MISMATCH")
	})

	t.Run("concurrent pointer switch pins in-flight map", func(t *testing.T) {
		waiting := holdFeatureReads(t, admin)
		pending := make(chan struct {
			response
			err error
		}, 1)
		go func() {
			got, err := request(t.Context(), synthetic.Client(), synthetic.URL+mapping)
			pending <- struct {
				response
				err error
			}{got, err}
		}()
		waiting.blocked(t)
		change(t, operator, a.scope, &b.releaseID, 1, "ACTIVATE")
		waiting.release(t)
		result := <-pending
		if result.err != nil {
			t.Fatal(result.err)
		}
		old := expectMap(t, result.response, "ACTIVE", "PARTIAL_SOURCE_COVERAGE", a, 1)
		if len(old.Features) != 4 || old.Features[3].ID != uid(108) {
			t.Fatalf("map snapshot lost a release A zone: %+v", old)
		}
		new := expectMap(t, get(t, synthetic, mapping), "ACTIVE", "PARTIAL_SOURCE_COVERAGE", b, 2)
		if len(new.Features) != 4 || new.Features[3].ID != uid(208) {
			t.Fatalf("new request did not read release B: %+v", new)
		}
	})

	t.Run("release scoped detail and cursor", func(t *testing.T) {
		oldDetail := expectDetail(t, get(t, synthetic, detail(uid(10), a.releaseID)), a, 1)
		if oldDetail.IsCurrent {
			t.Fatal("historical pin was labeled current")
		}
		expectDetail(t, get(t, synthetic, detail(uid(10), b.releaseID)), b, 2)
		assertError(t, get(t, synthetic, detail(uid(108), b.releaseID)), 404, "FEATURE_NOT_PUBLISHED")
		page := expectMap(t, get(t, synthetic, mapping+"&limit=2&cursor="+url.QueryEscape(next)), "ACTIVE", "PARTIAL_SOURCE_COVERAGE", a, 1)
		if len(page.Features) != 2 || page.Features[0].ID != uid(30) || page.Features[1].ID != uid(108) || page.Links.NextCursor != nil {
			t.Fatalf("cursor did not complete original release: %+v", page)
		}
	})

	t.Run("rollback, withdrawal and rights changes", func(t *testing.T) {
		change(t, operator, a.scope, &a.releaseID, 2, "ROLLBACK")
		expectMap(t, get(t, synthetic, mapping), "ACTIVE", "PARTIAL_SOURCE_COVERAGE", a, 3)
		change(t, operator, a.scope, nil, 3, "WITHDRAW")
		expectMap(t, get(t, synthetic, mapping), "WITHDRAWN", "NOT_ASSESSED", fixture{}, 4)
		assertError(t, get(t, synthetic, detail(uid(10), a.releaseID)), 410, "RELEASE_WITHDRAWN")
		assertError(t, get(t, synthetic, mapping+"&cursor="+url.QueryEscape(next)), 410, "RELEASE_WITHDRAWN")
		other := mapPath + "?scope=" + c.scope + "&bbox=0,0,0.1,0.1"
		expectMap(t, get(t, synthetic, other), "ACTIVE", "PARTIAL_SOURCE_COVERAGE", c, 1)
		execSQL(t, admin, "UPDATE sources.publication_scope SET reviewed_geom = public.ST_Multi(public.ST_MakeEnvelope(0,0,0.19,0.19,4326)) WHERE scope_key = $1", c.scope)
		expectMap(t, get(t, synthetic, other), "NO_PUBLIC_RELEASE", "NO_PUBLIC_RELEASE", fixture{}, 1)
		assertError(t, get(t, synthetic, other+"&release_id="+c.releaseID), 404, "RELEASE_NOT_FOUND")
		execSQL(t, admin, "UPDATE sources.source_dataset SET rights_status = 'WITHDRAWN' WHERE dataset_id = $1", c.datasetID)
		expectMap(t, get(t, synthetic, other), "WITHDRAWN", "NOT_ASSESSED", fixture{}, 1)
		assertError(t, get(t, synthetic, other+"&release_id="+c.releaseID), 410, "RELEASE_WITHDRAWN")
	})

	t.Run("database outage and recovery", func(t *testing.T) {
		container := os.Getenv("CURBOS_TEST_DB_CONTAINER")
		control := func(command string) error {
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			return exec.CommandContext(ctx, "docker", command, container).Run()
		}
		if err := control("pause"); err != nil {
			t.Fatal(err)
		}
		paused := true
		t.Cleanup(func() {
			if paused {
				if err := control("unpause"); err != nil {
					t.Error(err)
				}
			}
		})
		assertError(t, get(t, normal, mapping), 503, "DISCOVERY_UNAVAILABLE")
		if err := control("unpause"); err != nil {
			t.Fatal(err)
		}
		paused = false
		expectMap(t, get(t, normal, mapping), "NO_PUBLIC_RELEASE", "NO_PUBLIC_RELEASE", fixture{}, 0)
	})
}

func expectDetail(t *testing.T, got response, f fixture, version int64) zoneDetail {
	t.Helper()
	if got.status != 200 || got.header.Get("Cache-Control") != "no-store" {
		t.Fatalf("detail failed: %d %s", got.status, got.body)
	}
	d := decode[zoneDetail](t, got)
	if d.ReleaseID == nil || *d.ReleaseID != f.releaseID || d.PointerVersion != version ||
		d.DataStatus != "SYNTHETIC_TEST_DATA" || d.PublicEligible ||
		len(d.PolicyRefs) != 1 || d.PolicyRefs[0] != (policyReference{f.policyID, 0}) {
		t.Fatalf("detail did not pin evidence: %s", got.body)
	}
	expectEvidence(t, d.Feature, f)
	assertSafe(t, got)
	return d
}

type featureBarrier struct {
	admin  *pgxpool.Pool
	pid    int32
	unlock func() error
}

func holdFeatureReads(t *testing.T, admin *pgxpool.Pool) featureBarrier {
	t.Helper()
	tx, err := admin.Begin(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	unlock := func() error { return tx.Rollback(context.Background()) } // releases the table lock
	t.Cleanup(func() { _ = unlock() })
	var pid int32
	if err := tx.QueryRow(t.Context(), "SELECT pg_backend_pid()").Scan(&pid); err != nil {
		t.Fatal(err)
	}
	// The map accesses QA only after it pins a release. CAS never accesses QA.
	if _, err := tx.Exec(t.Context(), "LOCK TABLE sources.qa_issue IN ACCESS EXCLUSIVE MODE"); err != nil {
		t.Fatal(err)
	}
	return featureBarrier{admin, pid, unlock}
}

func (b featureBarrier) release(t *testing.T) {
	t.Helper()
	if err := b.unlock(); err != nil {
		t.Fatal(err)
	}
}

func (b featureBarrier) blocked(t *testing.T) {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 3*time.Second)
	defer cancel()
	tick := time.NewTicker(10 * time.Millisecond)
	defer tick.Stop()
	for {
		var blocked bool
		err := b.admin.QueryRow(ctx, `SELECT EXISTS (
			SELECT FROM pg_stat_activity
			WHERE application_name = 'discovery_test_synthetic'
			AND $1 = ANY(pg_blocking_pids(pid)))`, b.pid).Scan(&blocked)
		if err != nil {
			t.Fatal(err)
		}
		if blocked {
			return
		}
		select {
		case <-ctx.Done():
			t.Fatal("request never reached the feature-query barrier")
		case <-tick.C:
		}
	}
}
