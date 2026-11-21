package discovery

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func disposablePool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	if os.Getenv("CURBOS_API_INTEGRATION") != "1" {
		t.Skip("run make api-test to provision a disposable PostgreSQL database")
	}
	project, container := os.Getenv("COMPOSE_PROJECT_NAME"), os.Getenv("CURBOS_TEST_DB_CONTAINER")
	cfg, err := pgxpool.ParseConfig(os.Getenv("CURBOS_DATABASE_URL"))
	if err != nil || !regexp.MustCompile(`^curbos-db-test-[0-9a-f]{16}$`).MatchString(project) ||
		!regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(container) {
		t.Fatal("Discovery integration requires the isolated Compose database")
	}
	identity, err := exec.CommandContext(t.Context(), "docker", "inspect", "--format",
		`{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}} {{range index .NetworkSettings.Ports "5432/tcp"}}{{.HostIp}}:{{.HostPort}}{{end}}`, container).Output()
	c := cfg.ConnConfig
	endpoint := net.JoinHostPort(c.Host, strconv.Itoa(int(c.Port)))
	if err != nil || c.Host != "127.0.0.1" || c.User != "curbos" || c.Database != "curbos" ||
		len(c.Fallbacks) != 0 || strings.TrimSpace(string(identity)) != project+"/db "+endpoint {
		t.Fatal("database credentials do not target the isolated Compose container")
	}
	return openPool(t, cfg)
}

func openPool(t *testing.T, cfg *pgxpool.Config) *pgxpool.Pool {
	t.Helper()
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal("create test database pool")
	}
	t.Cleanup(pool.Close)
	if err := pool.Ping(t.Context()); err != nil {
		t.Fatal("authenticate test database login")
	}
	return pool
}

func testLogin(t *testing.T, admin *pgxpool.Pool, name string, roles ...string) *pgxpool.Pool {
	t.Helper()
	user := "discovery_test_" + name
	password := rand.Text()
	ident := pgx.Identifier{user}.Sanitize()
	execSQL(t, admin, fmt.Sprintf("CREATE ROLE %s LOGIN PASSWORD '%s'", ident, password))
	for _, role := range roles {
		execSQL(t, admin, "GRANT "+pgx.Identifier{role}.Sanitize()+" TO "+ident)
	}
	cfg := admin.Config()
	cfg.ConnConfig.User = user
	cfg.ConnConfig.Password = password
	cfg.ConnConfig.RuntimeParams["application_name"] = user
	return openPool(t, cfg)
}

func execSQL(t *testing.T, pool *pgxpool.Pool, statement string, args ...any) {
	t.Helper()
	if _, err := pool.Exec(t.Context(), statement, args...); err != nil {
		t.Fatal(err)
	}
}

func uid(n int) string { return fmt.Sprintf("00000000-0000-4000-8000-%012d", n) }

type fixture struct {
	scope, releaseID, datasetID, artifactID, policyID string
	longitude                                         json.Number
}

func seedFixture(t *testing.T, admin, registrar, verifier, reviewer *pgxpool.Pool, n int, scope string, freeze bool) fixture {
	t.Helper()
	f := fixture{scope, uid(n + 1), uid(n + 2), uid(n + 3), uid(n + 4), json.Number(fmt.Sprintf("0.0%d", n/100))}
	batchID, candidate, policyArtifact := uid(n+5), uid(n+6), uid(n+7)
	digest := strings.Repeat("1", 64)
	policyDigest := strings.Repeat("2", 64)
	execSQL(t, admin, `INSERT INTO sources.publication_scope
		(scope_key, display_name, reviewed_geom, review_status, reviewed_at)
		VALUES ($1, 'Synthetic', public.ST_Multi(public.ST_MakeEnvelope(0,0,0.2,0.2,4326)),
		'APPROVED', now()) ON CONFLICT DO NOTHING`, scope)
	execSQL(t, admin, `INSERT INTO sources.source_dataset
		(dataset_id, publisher_key, dataset_key, catalog_uri, source_profile, rights_status, rights_reference)
		VALUES ($1, 'synthetic-test', $2, 'https://synthetic-cds.invalid/catalog', 'synthetic-cds-json',
		'APPROVED', 'private-rights-reference')`, f.datasetID, "synthetic-"+f.datasetID)
	execSQL(t, admin, `INSERT INTO sources.raw_artifact
		(artifact_id, dataset_id, component_role, content_uri, content_sha256, byte_size, retrieved_at,
		 source_as_of, source_format, source_crs, metadata)
		VALUES ($1, $2, 'zones', 'cas+sha256:' || $3, $3, 1, now(), '2026-01-01T00:00:00Z', 'json',
		 'CRS84', '{"original_source_uri":"https://synthetic-cds.invalid/private-raw-zone"}'),
		($4, $2, 'policies', 'cas+sha256:' || $5, $5, 1, now(), NULL, 'json',
		 NULL, '{"original_source_uri":"https://synthetic-cds.invalid/private-raw-policy"}')`,
		f.artifactID, f.datasetID, digest, policyArtifact, policyDigest)
	execSQL(t, admin, `INSERT INTO sources.import_batch (batch_id, scope_key, adapter_version,
		source_profile_version, capture_manifest_sha256) VALUES ($1, $2, 'v1', 'v1', $3)`, batchID, scope, digest)
	execSQL(t, admin, `INSERT INTO sources.import_artifact VALUES ($1, 'zones', $2), ($1, 'policies', $3)`,
		batchID, f.artifactID, policyArtifact)
	execSQL(t, admin, `UPDATE sources.import_batch SET status = 'STAGED', validation_report_sha256 = $2 WHERE batch_id = $1`, batchID, digest)
	execSQL(t, admin, `INSERT INTO publication.synthetic_fixture VALUES ($1,$2,$3,$4)`, batchID, scope, f.datasetID, digest)

	lineage := map[string]any{
		"batch_id": batchID, "scope_key": scope, "dataset_id": f.datasetID, "adapter_version": "v1",
		"source_profile_version": "v1", "capture_manifest_sha256": digest, "stage_report_sha256": digest,
		"artifacts": map[string]any{
			"zones":    map[string]any{"artifact_id": f.artifactID, "byte_size": 1, "sha256": digest, "declared_source_crs": "CRS84"},
			"policies": map[string]any{"artifact_id": policyArtifact, "byte_size": 1, "sha256": policyDigest},
		},
	}
	var zones, links []map[string]any
	// Deliberately submit in reverse ID order. Most IDs are reused across releases.
	for _, id := range []string{uid(30), uid(20), uid(10), uid(n + 8)} {
		start, end := [2]json.Number{f.longitude, "0.01"}, [2]json.Number{f.longitude, "0.02"}
		geometry := lineString{Type: "LineString", Coordinates: [][2]json.Number{start, end}}
		if id == uid(10) {
			geometry.Coordinates = append(geometry.Coordinates, end)
		}
		zones = append(zones, map[string]any{"id": id, "geometry": geometry,
			"geometry_sha256": digest, "street_side": "LEFT", "road_reference": "fixture-road",
			"source_num_spaces": 99})
		links = append(links, map[string]any{"zone_id": id, "policy_id": f.policyID, "source_position": 0})
	}
	plan := map[string]any{
		"summary": map[string]any{}, "review_required": []string{}, "areas": []string{}, "area_zone_links": []string{},
		"zones": zones, "zone_policy_links": links,
		"policies": []map[string]any{{"id": f.policyID, "payload": map[string]string{"private": "fixture-policy-payload"}}},
		"qa": []map[string]any{{"role": "zones", "source_id": uid(10),
			"locator": "zones:0", "severity": "INFO", "disposition": "RETAINED", "reason": "ZONE_GEOMETRY_REPEATED_VERTEX"}},
	}
	args := []any{f.releaseID, candidate, digest, lineage, plan}
	execSQL(t, registrar, `SELECT publication.register_candidate($1,$2,$3,$4::jsonb,$5::jsonb)`, args...)
	if !freeze {
		return f
	}
	var verified struct {
		PlanSHA string `json:"plan_sha256"`
	}
	if err := verifier.QueryRow(t.Context(), `SELECT publication.verify_candidate($1,$2,$3,$4::jsonb,$5::jsonb)`, args...).Scan(&verified); err != nil {
		t.Fatal(err)
	}
	evidence := map[string]any{
		"candidate_report_sha256": digest, "plan_sha256": verified.PlanSHA, "artifact_rights": map[string]string{
			f.artifactID: "private-artifact-rights", policyArtifact: "private-artifact-rights",
		}, "review_exclusions": map[string]string{},
	}
	for _, gate := range []string{"qa", "rights", "scope", "coverage", "placement", "exclusion"} {
		evidence[gate+"_ref"] = "private-" + gate
	}
	execSQL(t, reviewer, `SELECT publication.approve_release($1,$2::jsonb)`, f.releaseID, evidence)
	execSQL(t, reviewer, `SELECT publication.freeze_release($1)`, f.releaseID)
	return f
}

func change(t *testing.T, operator *pgxpool.Pool, scope string, release *string, expected int, action string) {
	t.Helper()
	execSQL(t, operator, `SELECT publication.change_pointer($1,$2,$3,$4,$5,$6)`, scope, release, expected,
		action, "private operator reason", rand.Text())
}
