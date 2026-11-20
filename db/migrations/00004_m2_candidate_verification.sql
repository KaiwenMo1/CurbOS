-- +goose Up
-- Refuse to treat releases registered through the old SQL boundary as verified.
LOCK TABLE sources.dataset_release, publication.release_evidence IN ACCESS EXCLUSIVE MODE;
-- +goose StatementBegin
DO $$
BEGIN
    IF EXISTS (SELECT FROM publication.release_evidence)
       OR EXISTS (SELECT FROM sources.activation_event)
       OR EXISTS (SELECT FROM sources.active_release WHERE release_id IS NOT NULL) THEN
        RAISE EXCEPTION 'Legacy publication history requires independent review before upgrade';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'curbos_publication_verifier') THEN
        CREATE ROLE curbos_publication_verifier NOLOGIN;
    END IF;
    IF EXISTS (
        SELECT FROM pg_roles WHERE rolname = 'curbos_publication_verifier'
          AND (rolcanlogin OR rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls OR rolreplication)
    ) THEN
        RAISE EXCEPTION 'Unsafe publication verifier role';
    END IF;
END
$$;
-- +goose StatementEnd

CREATE TABLE publication.release_verification (
    -- The referenced, immutable registration contains the exact candidate and digests.
    release_id uuid PRIMARY KEY REFERENCES publication.release_evidence ON DELETE RESTRICT,
    verified_by name NOT NULL DEFAULT session_user,
    verified_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON publication.release_verification FROM PUBLIC;
CREATE TRIGGER protect_release_verification BEFORE UPDATE OR DELETE ON publication.release_verification
FOR EACH ROW EXECUTE FUNCTION publication.deny_mutation();
CREATE TRIGGER protect_release_verification_truncate BEFORE TRUNCATE ON publication.release_verification
FOR EACH STATEMENT EXECUTE FUNCTION publication.deny_mutation();

REVOKE EXECUTE ON FUNCTION publication.register_candidate(uuid, uuid, text, jsonb, jsonb)
    FROM curbos_publication_registrar;
ALTER FUNCTION publication.register_candidate(uuid, uuid, text, jsonb, jsonb)
    RENAME TO register_candidate_v3;

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION publication.guard_projection() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    parent_ids uuid[] := ARRAY[]::uuid[];
    parent sources.dataset_release%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN parent_ids := array_append(parent_ids, OLD.release_id); END IF;
    IF TG_OP <> 'DELETE' THEN parent_ids := array_append(parent_ids, NEW.release_id); END IF;
    -- A writer and a release transition must serialize on the parent row.
    FOR parent IN
        SELECT * FROM sources.dataset_release WHERE release_id = ANY(parent_ids)
        ORDER BY release_id FOR SHARE
    LOOP
        IF parent.status <> 'CANDIDATE' OR EXISTS (
            SELECT FROM publication.release_evidence WHERE release_id = parent.release_id
        ) THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RELEASE_PROJECTION_IMMUTABLE';
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$;
-- +goose StatementEnd

-- +goose StatementBegin
CREATE FUNCTION publication.register_candidate(
    p_release uuid, p_candidate uuid, p_report_sha text, p_lineage jsonb, p_plan jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    staged sources.import_batch%ROWTYPE;
    previous publication.release_evidence%ROWTYPE;
    plan_sha text := encode(sha256(convert_to(p_plan::text, 'UTF8')), 'hex');
    component_count integer;
    field text;
BEGIN
    PERFORM publication.require_role('curbos_publication_registrar');
    IF p_release IS NULL OR p_candidate IS NULL OR p_report_sha IS NULL
       OR p_report_sha !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_lineage->'artifacts') IS DISTINCT FROM 'object'
       OR NOT (p_lineage->'artifacts' ?& ARRAY['zones', 'policies'])
       OR jsonb_typeof(p_plan->'summary') IS DISTINCT FROM 'object'
       OR jsonb_typeof(p_plan->'review_required') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'CANDIDATE_EVIDENCE_INVALID';
    END IF;
    FOREACH field IN ARRAY ARRAY['zones', 'policies', 'areas', 'zone_policy_links', 'area_zone_links', 'qa'] LOOP
        IF jsonb_typeof(p_plan->field) IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'CANDIDATE_PROJECTION_INVALID';
        END IF;
    END LOOP;
    SELECT * INTO staged FROM sources.import_batch
    WHERE batch_id = (p_lineage->>'batch_id')::uuid FOR SHARE;
    IF NOT FOUND OR staged.status <> 'STAGED' OR staged.scope_key IS NULL
       OR staged.scope_key IS DISTINCT FROM p_lineage->>'scope_key'
       OR staged.capture_manifest_sha256 IS DISTINCT FROM p_lineage->>'capture_manifest_sha256'
       OR staged.validation_report_sha256 IS NULL
       OR staged.validation_report_sha256 IS DISTINCT FROM p_lineage->>'stage_report_sha256'
       OR staged.adapter_version IS DISTINCT FROM p_lineage->>'adapter_version'
       OR staged.source_profile_version IS DISTINCT FROM p_lineage->>'source_profile_version' THEN
        RAISE EXCEPTION 'CANDIDATE_BATCH_LINEAGE_MISMATCH';
    END IF;

    SELECT count(*) INTO component_count FROM sources.import_artifact WHERE batch_id = staged.batch_id;
    IF component_count <> (SELECT count(*) FROM jsonb_object_keys(p_lineage->'artifacts'))
       OR EXISTS (
          SELECT FROM sources.import_artifact j
          JOIN sources.raw_artifact a USING (artifact_id)
          WHERE j.batch_id = staged.batch_id AND (
              j.component_role NOT IN ('zones', 'policies', 'areas')
              OR a.component_role <> j.component_role
              OR a.dataset_id::text IS DISTINCT FROM p_lineage->>'dataset_id'
              OR a.artifact_id::text IS DISTINCT FROM p_lineage->'artifacts'->j.component_role->>'artifact_id'
              OR a.content_sha256 IS DISTINCT FROM p_lineage->'artifacts'->j.component_role->>'sha256'
              OR a.byte_size::text IS DISTINCT FROM p_lineage->'artifacts'->j.component_role->>'byte_size'
              OR a.content_uri <> 'cas+sha256:' || a.content_sha256
          ))
       OR EXISTS (
          SELECT FROM sources.import_artifact WHERE batch_id = staged.batch_id
          GROUP BY component_role HAVING count(*) <> 1
       ) THEN
        RAISE EXCEPTION 'CANDIDATE_ARTIFACT_LINEAGE_MISMATCH';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended('candidate:' || p_candidate::text, 302));
    SELECT * INTO previous FROM publication.release_evidence WHERE candidate_id = p_candidate;
    IF FOUND THEN
        IF (previous.release_id, previous.report_sha256, previous.plan_sha256, previous.lineage)
           IS DISTINCT FROM (p_release, p_report_sha, plan_sha, p_lineage) THEN
            RAISE EXCEPTION 'CANDIDATE_REPLAY_CONFLICT';
        END IF;
    ELSE
        INSERT INTO sources.dataset_release
            (release_id, batch_id, scope_key, validation_report_sha256, exclusion_summary)
        VALUES (p_release, staged.batch_id, staged.scope_key, p_report_sha, p_plan->'summary');
        INSERT INTO rules.release_policy_definition (release_id, source_policy_id, source_jsonb, parse_status)
        SELECT p_release, id, payload, 'PASSED'
        FROM jsonb_to_recordset(p_plan->'policies') AS rows(id text, payload jsonb);

        INSERT INTO geo.release_curb_zone
            (release_id, source_zone_id, raw_artifact_id, source_crs, geom, geometry_sha256,
             street_side, road_reference, geometry_evidence, policy_ref_status, source_num_spaces)
        SELECT p_release, id, (p_lineage->'artifacts'->'zones'->>'artifact_id')::uuid,
               p_lineage->'artifacts'->'zones'->>'declared_source_crs',
               publication.source_geometry(geometry, 'zones'), geometry_sha256,
               street_side, road_reference, 'SOURCE_REPORTED', 'COMPLETE', source_num_spaces
        FROM jsonb_to_recordset(p_plan->'zones') AS rows(
            id text, geometry jsonb, geometry_sha256 text, street_side text,
            road_reference text, source_num_spaces integer
        );

        INSERT INTO rules.release_zone_policy_link (release_id, source_zone_id, source_policy_id, source_position)
        SELECT p_release, zone_id, policy_id, source_position
        FROM jsonb_to_recordset(p_plan->'zone_policy_links') AS links(
            zone_id text, policy_id text, source_position integer
        );
        IF EXISTS (
            SELECT FROM geo.release_curb_zone z
            WHERE z.release_id = p_release AND NOT EXISTS (
                SELECT FROM rules.release_zone_policy_link l
                WHERE l.release_id = z.release_id AND l.source_zone_id = z.source_zone_id
            )
        ) THEN
            RAISE EXCEPTION 'CANDIDATE_ZONE_POLICY_MISSING';
        END IF;

        INSERT INTO sources.release_area
            (release_id, source_area_id, raw_artifact_id, name, description, source_geometry_type, display_geom)
        SELECT p_release, id, (p_lineage->'artifacts'->'areas'->>'artifact_id')::uuid,
               name, description, geometry->>'type',
               publication.source_geometry(geometry, 'areas')
        FROM jsonb_to_recordset(p_plan->'areas') AS rows(
            id text, name text, description text, geometry jsonb
        );
        IF EXISTS (SELECT FROM sources.release_area WHERE release_id = p_release AND display_geom IS NULL) THEN
            RAISE EXCEPTION 'CANDIDATE_AREA_GEOMETRY_UNREPRESENTABLE';
        END IF;

        INSERT INTO sources.release_area_zone (release_id, source_area_id, source_zone_id)
        SELECT p_release, area_id, zone_id
        FROM jsonb_to_recordset(p_plan->'area_zone_links') AS links(area_id text, zone_id text);

        INSERT INTO sources.qa_issue
            (qa_id, batch_id, release_id, source_object_type, source_object_id,
             issue_code, severity, disposition, evidence_ref)
        SELECT gen_random_uuid(), staged.batch_id, p_release, role, source_id,
               reason, severity, disposition, 'candidate:' || p_candidate::text || '/' || locator
        FROM jsonb_to_recordset(p_plan->'qa') AS issues(
            role text, source_id text, reason text, severity text, disposition text, locator text
        );
        -- Seal the submitted projection once all rows have been inserted.
        INSERT INTO publication.release_evidence
            (release_id, candidate_id, report_sha256, plan_sha256, lineage, review_required)
        VALUES (
            p_release, p_candidate, p_report_sha, plan_sha, p_lineage,
            ARRAY(SELECT jsonb_array_elements_text(p_plan->'review_required'))
        );
    END IF;
    RETURN jsonb_build_object(
        'release_id', p_release, 'candidate_report_sha256', p_report_sha,
        'plan_sha256', plan_sha, 'status', (SELECT status FROM sources.dataset_release WHERE release_id = p_release)
    );
END
$$;
-- +goose StatementEnd

-- +goose StatementBegin
CREATE FUNCTION publication.verify_candidate(
    p_release uuid, p_candidate uuid, p_report_sha text, p_lineage jsonb, p_plan jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp SET timezone = 'UTC' AS $$
DECLARE
    registered publication.release_evidence%ROWTYPE;
    receipt publication.release_verification%ROWTYPE;
    release_status text;
    plan_digest text := encode(sha256(convert_to(p_plan::text, 'UTF8')), 'hex');
BEGIN
    PERFORM publication.require_role('curbos_publication_verifier');
    -- Serialize verifier retries and the transition with subsequent approval.
    SELECT status INTO release_status FROM sources.dataset_release WHERE release_id = p_release FOR UPDATE;
    SELECT * INTO registered FROM publication.release_evidence WHERE release_id = p_release;
    IF NOT FOUND THEN RAISE EXCEPTION 'CANDIDATE_REGISTRATION_REQUIRED'; END IF;
    IF registered.registered_by = session_user THEN RAISE EXCEPTION 'INDEPENDENT_VERIFIER_REQUIRED'; END IF;
    IF (registered.candidate_id, registered.report_sha256, registered.lineage, registered.plan_sha256)
       IS DISTINCT FROM (p_candidate, p_report_sha, p_lineage, plan_digest) THEN
        RAISE EXCEPTION 'CANDIDATE_VERIFICATION_MISMATCH';
    END IF;
    SELECT * INTO receipt FROM publication.release_verification WHERE release_id = p_release;
    IF NOT FOUND THEN
        IF release_status IS DISTINCT FROM 'CANDIDATE' THEN
            RAISE EXCEPTION 'CANDIDATE_VERIFICATION_STATE_INVALID';
        END IF;
        INSERT INTO publication.release_verification (release_id)
        VALUES (p_release) RETURNING * INTO receipt;
        UPDATE sources.dataset_release SET status = 'VALIDATED' WHERE release_id = p_release;
        release_status := 'VALIDATED';
    END IF;
    RETURN jsonb_build_object(
        'release_id', p_release, 'candidate_report_sha256', registered.report_sha256,
        'plan_sha256', registered.plan_sha256, 'status', release_status,
        'verified_by', receipt.verified_by, 'verified_at', receipt.verified_at
    );
END
$$;

CREATE FUNCTION publication.require_candidate_verification() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NOT EXISTS (SELECT FROM publication.release_verification WHERE release_id = NEW.release_id) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'CANDIDATE_VERIFICATION_REQUIRED';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION publication.require_independent_reviewer() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM publication.release_verification v
        WHERE v.release_id = NEW.release_id AND v.verified_by <> NEW.approved_by
    ) THEN
        RAISE EXCEPTION 'REVIEWER_MUST_BE_INDEPENDENT_OF_VERIFIER';
    END IF;
    RETURN NEW;
END
$$;
-- +goose StatementEnd

CREATE TRIGGER require_candidate_verification BEFORE UPDATE ON sources.dataset_release
FOR EACH ROW WHEN (NEW.status = 'VALIDATED') EXECUTE FUNCTION publication.require_candidate_verification();
CREATE TRIGGER require_independent_reviewer BEFORE INSERT ON publication.release_approval
FOR EACH ROW EXECUTE FUNCTION publication.require_independent_reviewer();

REVOKE EXECUTE ON FUNCTION publication.register_candidate(uuid, uuid, text, jsonb, jsonb),
    publication.verify_candidate(uuid, uuid, text, jsonb, jsonb),
    publication.require_candidate_verification(), publication.require_independent_reviewer() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION publication.register_candidate(uuid, uuid, text, jsonb, jsonb)
    TO curbos_publication_registrar;
GRANT USAGE ON SCHEMA publication, sources TO curbos_publication_verifier;
GRANT SELECT ON sources.import_batch, sources.import_artifact, sources.raw_artifact,
    sources.publication_scope TO curbos_publication_verifier;
GRANT EXECUTE ON FUNCTION publication.source_geometry(jsonb, text),
    publication.verify_candidate(uuid, uuid, text, jsonb, jsonb) TO curbos_publication_verifier;

-- +goose Down
LOCK TABLE sources.dataset_release, publication.release_evidence IN ACCESS EXCLUSIVE MODE;
-- +goose StatementBegin
DO $$
BEGIN
    IF EXISTS (SELECT FROM publication.release_evidence) THEN
        RAISE EXCEPTION 'Publication registrations exist. Dispose only of isolated test databases.';
    END IF;
END
$$;
-- +goose StatementEnd

DROP TRIGGER require_candidate_verification ON sources.dataset_release;
DROP TRIGGER require_independent_reviewer ON publication.release_approval;
DROP FUNCTION publication.require_candidate_verification();
DROP FUNCTION publication.require_independent_reviewer();
DROP FUNCTION publication.verify_candidate(uuid, uuid, text, jsonb, jsonb);
DROP FUNCTION publication.register_candidate(uuid, uuid, text, jsonb, jsonb);
DROP TABLE publication.release_verification;
REVOKE EXECUTE ON FUNCTION publication.source_geometry(jsonb, text) FROM curbos_publication_verifier;
REVOKE SELECT ON sources.import_batch, sources.import_artifact, sources.raw_artifact,
    sources.publication_scope FROM curbos_publication_verifier;
REVOKE USAGE ON SCHEMA publication, sources FROM curbos_publication_verifier;
ALTER FUNCTION publication.register_candidate_v3(uuid, uuid, text, jsonb, jsonb)
    RENAME TO register_candidate;
GRANT EXECUTE ON FUNCTION publication.register_candidate(uuid, uuid, text, jsonb, jsonb)
    TO curbos_publication_registrar;

-- +goose StatementBegin
CREATE OR REPLACE FUNCTION publication.guard_projection() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    parent_ids uuid[] := ARRAY[]::uuid[];
    parent_status text;
BEGIN
    IF TG_OP <> 'INSERT' THEN parent_ids := array_append(parent_ids, OLD.release_id); END IF;
    IF TG_OP <> 'DELETE' THEN parent_ids := array_append(parent_ids, NEW.release_id); END IF;
    -- A writer and a release transition must serialize on the parent row.
    FOR parent_status IN
        SELECT status FROM sources.dataset_release WHERE release_id = ANY(parent_ids)
        ORDER BY release_id FOR SHARE
    LOOP
        IF parent_status <> 'CANDIDATE' THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RELEASE_PROJECTION_IMMUTABLE';
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$;
-- +goose StatementEnd
