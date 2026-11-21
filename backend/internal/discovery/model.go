package discovery

import (
	"context"
	"encoding/json"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type release struct {
	Scope            string     `json:"scope"`
	PublicationState string     `json:"publication_state"`
	DataStatus       string     `json:"data_status"`
	ReleaseID        *string    `json:"release_id"`
	PointerVersion   int64      `json:"pointer_version"`
	IsCurrent        bool       `json:"is_current"`
	PublicEligible   bool       `json:"public_eligible"`
	ActivatedAt      *time.Time `json:"activated_at"`
	SourceAsOf       *time.Time `json:"source_as_of"`
	Attribution      []string   `json:"attribution"`
	Limitations      []string   `json:"limitations"`
}

type zoneFeature struct {
	Type       string         `json:"type"`
	ID         string         `json:"id"`
	Geometry   lineString     `json:"geometry"`
	Properties zoneProperties `json:"properties"`
}

type lineString struct {
	Type        string           `json:"type"`
	Coordinates [][2]json.Number `json:"coordinates"`
}

type zoneProperties struct {
	SourceZoneID          string     `json:"source_zone_id"`
	Publisher             string     `json:"publisher"`
	SourceAsOf            *time.Time `json:"source_as_of"`
	SourceArtifactID      string     `json:"source_artifact_id"`
	GeometrySHA256        string     `json:"geometry_sha256"`
	GeometryEvidence      string     `json:"geometry_evidence"`
	CurbPlacement         string     `json:"curb_placement"`
	StreetSide            *string    `json:"street_side"`
	RoadReference         *string    `json:"road_reference"`
	PolicyReferenceStatus string     `json:"policy_reference_status"`
	ParkingLegality       string     `json:"parking_legality"`
	Occupancy             string     `json:"occupancy"`
	Availability          string     `json:"availability"`
	QACodes               []string   `json:"qa_codes"`
}

type policyReference struct {
	SourcePolicyID string `json:"source_policy_id"`
	SourcePosition int    `json:"source_position"`
}

type mapMeta struct {
	release
	Coverage   string      `json:"coverage_status"`
	Request    string      `json:"request_status"`
	Exclusions []exclusion `json:"exclusions"`
}

type exclusion struct {
	Reason      string `json:"reason"`
	Count       *int   `json:"count"`
	CountStatus string `json:"count_status"`
}

type mapResponse struct {
	Type     string        `json:"type"`
	Features []zoneFeature `json:"features"`
	Meta     mapMeta       `json:"meta"`
	Links    mapLinks      `json:"links"`
}

type mapLinks struct {
	NextCursor *string `json:"next_cursor"`
}

type zoneDetail struct {
	release
	Feature    zoneFeature       `json:"feature"`
	PolicyRefs []policyReference `json:"policy_references"`
}

type result struct {
	release
	Coverage   string            `json:"coverage_status"`
	Features   []zoneFeature     `json:"features"`
	Feature    zoneFeature       `json:"feature"`
	PolicyRefs []policyReference `json:"policy_references"`
	ErrorCode  string            `json:"error_code"`
}

func read(ctx context.Context, pool *pgxpool.Pool, q query, synthetic bool) (result, error) {
	r := result{release: release{
		Scope: q.scope, PublicationState: "NO_PUBLIC_RELEASE", DataStatus: "NO_ACTIVE_RELEASE",
		Attribution: []string{}, Limitations: []string{"NO_AUTHORIZED_PUBLIC_PARKING_EVIDENCE"},
	}, Coverage: "NO_PUBLIC_RELEASE"}
	if !synthetic {
		var known bool
		if err := pool.QueryRow(ctx, "SELECT discovery.scope_known($1)", q.scope).Scan(&known); err != nil {
			return result{}, err
		}
		if !known {
			r.ErrorCode = "SCOPE_UNKNOWN"
		} else if q.pin != "" {
			r.ErrorCode = "RELEASE_NOT_FOUND"
		}
		return r, nil
	}

	const statement = `SELECT discovery.read_synthetic(
		$1, NULLIF($2::text, '')::uuid, $3, NULLIF($4::text, ''), $5, NULLIF($6::text, ''))`
	var raw []byte
	if err := pool.QueryRow(ctx, statement, q.scope, q.pin, q.bbox, q.after, q.limit, q.zone).Scan(&raw); err != nil {
		return result{}, err
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		return result{}, err
	}
	if r.ReleaseID != nil {
		r.DataStatus = "SYNTHETIC_TEST_DATA"
		r.Attribution = []string{"CurbOS synthetic test fixtures"}
		r.Limitations = []string{"DISCOVERY_ONLY", "CURB_PLACEMENT_UNVERIFIED", "PARKING_RULES_AVAILABILITY_AND_FIT_UNVERIFIED"}
	} else if r.PublicationState == "WITHDRAWN" {
		r.DataStatus = "WITHDRAWN"
	}
	return r, nil
}
