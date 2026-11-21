-- +goose Up
CREATE SCHEMA discovery;
REVOKE ALL ON SCHEMA discovery FROM PUBLIC;

-- +goose StatementBegin
DO $$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['curbos_api_reader', 'curbos_api_synthetic_reader'] LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', role_name);
        END IF;
        IF EXISTS (
            SELECT FROM pg_roles WHERE rolname = role_name
              AND (rolcanlogin OR rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls OR rolreplication)
        ) THEN
            RAISE EXCEPTION 'Unsafe Discovery capability role: %', role_name;
        END IF;
    END LOOP;
END
$$;
-- +goose StatementEnd

GRANT SELECT (id, version_id, is_applied) ON public.goose_db_version TO curbos_api_reader;
GRANT USAGE ON SCHEMA discovery TO curbos_api_reader, curbos_api_synthetic_reader;

CREATE FUNCTION discovery.scope_known(p_scope text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp
RETURN EXISTS (SELECT FROM sources.publication_scope WHERE scope_key = p_scope);

CREATE INDEX discovery_zone_order_idx ON geo.release_curb_zone (release_id, source_zone_id COLLATE "C");
CREATE INDEX discovery_activation_target_idx ON sources.activation_event
    (scope_key, to_release_id, pointer_version_after DESC) WHERE to_release_id IS NOT NULL;
CREATE INDEX discovery_withdrawal_idx ON sources.activation_event
    (scope_key, from_release_id) WHERE action = 'WITHDRAW';

-- +goose StatementBegin
CREATE FUNCTION discovery.zone_feature(z geo.release_curb_zone, publisher text) RETURNS jsonb
LANGUAGE sql STABLE SET search_path = pg_catalog, pg_temp AS $$
    SELECT jsonb_build_object(
        'type', 'Feature', 'id', z.source_zone_id,
        'geometry', public.ST_AsGeoJSON(z.geom, 17, 0)::jsonb,
        'properties', jsonb_build_object(
            'source_zone_id', z.source_zone_id,
            'publisher', publisher,
            'source_as_of', a.source_as_of,
            'source_artifact_id', z.raw_artifact_id,
            'geometry_sha256', z.geometry_sha256,
            'geometry_evidence', z.geometry_evidence,
            'curb_placement', 'UNVERIFIED',
            'street_side', z.street_side,
            'road_reference', z.road_reference,
            'policy_reference_status', 'RESOLVED_REFERENCES_ONLY',
            'parking_legality', 'UNKNOWN',
            'occupancy', 'UNKNOWN',
            'availability', 'UNKNOWN',
            'qa_codes', COALESCE((
                SELECT jsonb_agg(DISTINCT q.issue_code ORDER BY q.issue_code)
                FROM sources.qa_issue q
                WHERE q.release_id = z.release_id AND q.source_object_type = 'zones'
                  AND q.source_object_id = z.source_zone_id AND q.disposition = 'RETAINED'
                  AND q.issue_code IN ('ZONE_GEOMETRY_REPEATED_VERTEX')
            ), '[]'::jsonb)
        )
    )
    FROM sources.raw_artifact a WHERE a.artifact_id = z.raw_artifact_id;
$$;

-- All reads in this function use the calling statement's snapshot. The regular
-- API role has no execution grant. The Go binary has no synthetic runtime flag.
CREATE FUNCTION discovery.read_synthetic(
    p_scope text, p_pin uuid, p_bbox double precision[], p_after text, p_limit integer, p_zone text
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET timezone = 'UTC' AS $$
DECLARE
    scope_row sources.publication_scope%ROWTYPE;
    pointer sources.active_release%ROWTYPE;
    release_row sources.dataset_release%ROWTYPE;
    activated sources.activation_event%ROWTYPE;
    source_row sources.source_dataset%ROWTYPE;
    selected uuid;
    revoked boolean;
    safe_release boolean;
    viewport public.geometry;
    coverage text := 'NOT_ASSESSED';
    state text := 'NO_PUBLIC_RELEASE';
    metadata jsonb;
    features jsonb := '[]'::jsonb;
    feature jsonb;
    policies jsonb := '[]'::jsonb;
BEGIN
    IF p_bbox IS NOT NULL AND (cardinality(p_bbox) <> 4
       OR COALESCE(p_limit, 0) NOT BETWEEN 1 AND 250
       OR NOT COALESCE(p_bbox[1] >= -180 AND p_bbox[3] <= 180
           AND p_bbox[2] >= -90 AND p_bbox[4] <= 90
           AND p_bbox[3] - p_bbox[1] > 0 AND p_bbox[3] - p_bbox[1] <= 0.25
           AND p_bbox[4] - p_bbox[2] > 0 AND p_bbox[4] - p_bbox[2] <= 0.25, false)) THEN
        RAISE EXCEPTION 'Invalid Discovery viewport';
    END IF;

    SELECT * INTO scope_row FROM sources.publication_scope WHERE scope_key = p_scope;
    IF NOT FOUND THEN RETURN jsonb_build_object('error_code', 'SCOPE_UNKNOWN'); END IF;

    SELECT * INTO pointer FROM sources.active_release WHERE scope_key = p_scope;
    selected := COALESCE(p_pin, pointer.release_id);
    SELECT * INTO release_row FROM sources.dataset_release
    WHERE release_id = selected AND scope_key = p_scope AND status = 'FROZEN';
    IF FOUND THEN
        SELECT e.* INTO activated
        FROM sources.activation_event e
        WHERE e.scope_key = p_scope AND e.to_release_id = release_row.release_id
        ORDER BY e.pointer_version_after DESC LIMIT 1;

        SELECT d.* INTO source_row
        FROM publication.release_evidence r
        JOIN sources.source_dataset d ON d.dataset_id = (r.lineage->>'dataset_id')::uuid
        WHERE r.release_id = selected;

        revoked := scope_row.review_status = 'WITHDRAWN'
            OR source_row.rights_status IN ('DENIED', 'WITHDRAWN')
            OR EXISTS (
                SELECT FROM sources.activation_event
                WHERE scope_key = p_scope AND from_release_id = selected AND action = 'WITHDRAW'
            );
        -- This digest binds the approval to the reviewed boundary whose containment
        -- PR-04 checked before activation. The frozen projections are immutable.
        safe_release := activated.event_id IS NOT NULL AND NOT revoked
            AND scope_row.review_status = 'APPROVED' AND scope_row.reviewed_at IS NOT NULL
            AND scope_row.reviewed_geom IS NOT NULL
            AND source_row.rights_status = 'APPROVED'
            AND NULLIF(btrim(source_row.rights_reference), '') IS NOT NULL
            AND source_row.publisher_key = 'synthetic-test'
            AND source_row.source_profile = 'synthetic-cds-json'
            AND source_row.dataset_key ~ '^synthetic-'
            AND source_row.catalog_uri ~ '^https://synthetic-cds[.]invalid/'
            AND p_scope ~ '^synthetic-'
            AND EXISTS (
                SELECT FROM publication.release_evidence r
                JOIN publication.release_verification v USING (release_id)
                JOIN publication.release_approval a USING (release_id)
                JOIN publication.synthetic_fixture f ON f.batch_id = release_row.batch_id
                WHERE r.release_id = selected
                  AND f.scope_key = p_scope AND f.dataset_id = source_row.dataset_id
                  AND f.stage_sha256 = r.lineage->>'stage_report_sha256'
                  AND a.reviewed_scope_sha256 =
                      encode(sha256(public.ST_AsEWKB(scope_row.reviewed_geom, 'XDR')), 'hex')
            )
            AND NOT EXISTS (
                SELECT FROM sources.import_artifact j JOIN sources.raw_artifact a USING (artifact_id)
                WHERE j.batch_id = release_row.batch_id
                  AND (a.dataset_id <> source_row.dataset_id
                      OR COALESCE(a.metadata->>'original_source_uri', '') !~ '^https://synthetic-cds[.]invalid/')
            );
    END IF;

    IF safe_release IS NOT TRUE THEN
        IF p_pin IS NOT NULL THEN
            IF revoked AND activated.event_id IS NOT NULL THEN
                RETURN jsonb_build_object('error_code', 'RELEASE_WITHDRAWN');
            END IF;
            RETURN jsonb_build_object('error_code', 'RELEASE_NOT_FOUND');
        END IF;
        IF (revoked AND activated.event_id IS NOT NULL)
            OR (pointer.release_id IS NULL AND pointer.pointer_version > 0) THEN
            state := 'WITHDRAWN';
        ELSE
            coverage := 'NO_PUBLIC_RELEASE';
        END IF;
        RETURN jsonb_build_object('publication_state', state, 'coverage_status', coverage,
            'pointer_version', COALESCE(pointer.pointer_version, 0));
    END IF;

    metadata := jsonb_build_object(
        'release_id', selected, 'publication_state', 'ACTIVE',
        'is_current', selected IS NOT DISTINCT FROM pointer.release_id,
        'pointer_version', activated.pointer_version_after, 'activated_at', activated.happened_at,
        'source_as_of', COALESCE(release_row.source_as_of, (
            SELECT a.source_as_of FROM sources.import_artifact j JOIN sources.raw_artifact a USING (artifact_id)
            WHERE j.batch_id = release_row.batch_id AND j.component_role = 'zones'
        ))
    );
    IF p_bbox IS NOT NULL THEN
        viewport := public.ST_MakeEnvelope(p_bbox[1], p_bbox[2], p_bbox[3], p_bbox[4], 4326);
        IF NOT public.ST_Intersects(viewport, scope_row.reviewed_geom) THEN
            coverage := 'OUTSIDE_REVIEWED_SCOPE';
        ELSE
            SELECT COALESCE(jsonb_agg(discovery.zone_feature(page.zone, source_row.publisher_key)
                                     ORDER BY (page.zone).source_zone_id COLLATE "C"), '[]'::jsonb)
            INTO features
            FROM (
                SELECT z AS zone FROM geo.release_curb_zone z
                WHERE z.release_id = selected
                  AND (p_after IS NULL OR z.source_zone_id COLLATE "C" > p_after COLLATE "C")
                  AND z.policy_ref_status = 'COMPLETE' AND z.geometry_evidence = 'SOURCE_REPORTED'
                  AND z.street_side IN ('LEFT', 'RIGHT')
                  AND public.ST_Intersects(z.geom, viewport)
                ORDER BY z.source_zone_id COLLATE "C"
                LIMIT p_limit + 1
            ) AS page;
            IF jsonb_array_length(features) = 0 AND public.ST_CoveredBy(viewport, scope_row.reviewed_geom) THEN
                coverage := 'ASSESSED_NO_SOURCE_FEATURES';
            ELSE
                coverage := 'PARTIAL_SOURCE_COVERAGE';
            END IF;
        END IF;
    ELSIF p_zone IS NOT NULL THEN
        SELECT discovery.zone_feature(z, source_row.publisher_key) INTO feature
        FROM geo.release_curb_zone z
        WHERE z.release_id = selected AND z.source_zone_id = p_zone
          AND z.policy_ref_status = 'COMPLETE' AND z.geometry_evidence = 'SOURCE_REPORTED'
          AND z.street_side IN ('LEFT', 'RIGHT');
        IF NOT FOUND THEN RETURN jsonb_build_object('error_code', 'FEATURE_NOT_PUBLISHED'); END IF;
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
            'source_policy_id', source_policy_id, 'source_position', source_position
        ) ORDER BY source_position, source_policy_id COLLATE "C"), '[]'::jsonb) INTO policies
        FROM rules.release_zone_policy_link
        WHERE release_id = selected AND source_zone_id = p_zone;
        RETURN metadata || jsonb_build_object('feature', feature, 'policy_references', policies);
    END IF;
    RETURN metadata || jsonb_build_object('features', features, 'coverage_status', coverage);
END
$$;
-- +goose StatementEnd

REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA discovery FROM PUBLIC;
GRANT EXECUTE ON FUNCTION discovery.scope_known(text) TO curbos_api_reader;
GRANT EXECUTE ON FUNCTION discovery.read_synthetic(text, uuid, double precision[], text, integer, text)
TO curbos_api_synthetic_reader;

-- +goose Down
DROP SCHEMA discovery CASCADE;
DROP INDEX geo.discovery_zone_order_idx;
DROP INDEX sources.discovery_activation_target_idx;
DROP INDEX sources.discovery_withdrawal_idx;
REVOKE SELECT (id, version_id, is_applied) ON public.goose_db_version FROM curbos_api_reader;
-- Capability group names are cluster-wide and can be reused by other databases.
