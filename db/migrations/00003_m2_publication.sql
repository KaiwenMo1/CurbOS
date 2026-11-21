-- +goose Up
CREATE SCHEMA publication;

-- +goose StatementBegin
DO $$
DECLARE
    role_name text;
BEGIN
    IF EXISTS (SELECT FROM sources.active_release WHERE release_id IS NOT NULL)
       OR EXISTS (SELECT FROM sources.activation_event)
       OR EXISTS (SELECT FROM sources.dataset_release WHERE status IN ('APPROVED', 'FROZEN')) THEN
        RAISE EXCEPTION 'Publication migration requires an unactivated baseline';
    END IF;
    FOREACH role_name IN ARRAY ARRAY[
        'curbos_publication_registrar', 'curbos_publication_reviewer', 'curbos_publication_operator',
        'curbos_publication_executor'
    ] LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', role_name);
        END IF;
        IF EXISTS (
            SELECT FROM pg_roles WHERE rolname = role_name
              AND (rolcanlogin OR rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls OR rolreplication)
        ) THEN
            RAISE EXCEPTION 'Unsafe publication capability role: %', role_name;
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT FROM pg_auth_members m
        JOIN pg_roles r ON r.oid = m.roleid
        WHERE r.rolname = 'curbos_publication_executor'
    ) THEN
        RAISE EXCEPTION 'Publication executor must have no members';
    END IF;
END
$$;
-- +goose StatementEnd

CREATE TABLE publication.release_evidence (
    release_id uuid PRIMARY KEY REFERENCES sources.dataset_release ON DELETE RESTRICT,
    candidate_id uuid NOT NULL UNIQUE,
    report_sha256 text NOT NULL CHECK (report_sha256 ~ '^[0-9a-f]{64}$'),
    plan_sha256 text NOT NULL CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    review_required text[] NOT NULL,
    registered_by name NOT NULL DEFAULT session_user
);

CREATE TABLE publication.release_approval (
    release_id uuid PRIMARY KEY REFERENCES publication.release_evidence ON DELETE RESTRICT,
    evidence jsonb NOT NULL,
    reviewed_scope_sha256 text NOT NULL,
    approved_by name NOT NULL DEFAULT session_user,
    approved_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- This table starts empty. Only a database administrator in the disposable test
-- harness enrolls a batch, binding it to its scope, dataset and stage digest.
CREATE TABLE publication.synthetic_fixture (
    batch_id uuid PRIMARY KEY REFERENCES sources.import_batch ON DELETE RESTRICT,
    scope_key text NOT NULL REFERENCES sources.publication_scope ON DELETE RESTRICT,
    dataset_id uuid NOT NULL REFERENCES sources.source_dataset ON DELETE RESTRICT,
    stage_sha256 text NOT NULL CHECK (stage_sha256 ~ '^[0-9a-f]{64}$')
);

-- +goose StatementBegin
CREATE FUNCTION publication.deny_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'PUBLICATION_EVIDENCE_IMMUTABLE';
END
$$;

CREATE FUNCTION publication.guard_batch() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF OLD.status = 'STAGED' THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'STAGED_BATCH_IMMUTABLE';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION publication.guard_artifact_link() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    parent_ids uuid[] := ARRAY[]::uuid[];
    parent_status text;
BEGIN
    IF TG_OP <> 'INSERT' THEN parent_ids := array_append(parent_ids, OLD.batch_id); END IF;
    IF TG_OP <> 'DELETE' THEN parent_ids := array_append(parent_ids, NEW.batch_id); END IF;
    FOR parent_status IN
        SELECT status FROM sources.import_batch WHERE batch_id = ANY(parent_ids)
        ORDER BY batch_id FOR SHARE
    LOOP
        IF parent_status = 'STAGED' THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'STAGED_ARTIFACT_LINK_IMMUTABLE';
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION publication.guard_dataset_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF (OLD.dataset_id, OLD.publisher_key, OLD.dataset_key, OLD.catalog_uri, OLD.source_profile)
        IS DISTINCT FROM
       (NEW.dataset_id, NEW.publisher_key, NEW.dataset_key, NEW.catalog_uri, NEW.source_profile) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'SOURCE_DATASET_IDENTITY_IMMUTABLE';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION publication.guard_release() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'CANDIDATE' THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RELEASE_IMMUTABLE';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'CANDIDATE' THEN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RELEASE_TRANSITION_INVALID';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'FROZEN' OR
       (OLD.release_id, OLD.batch_id, OLD.scope_key, OLD.validation_report_sha256,
        OLD.exclusion_summary, OLD.source_as_of)
       IS DISTINCT FROM
       (NEW.release_id, NEW.batch_id, NEW.scope_key, NEW.validation_report_sha256,
        NEW.exclusion_summary, NEW.source_as_of) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RELEASE_IMMUTABLE';
    END IF;
    IF NOT (
        (OLD.status = 'CANDIDATE' AND NEW.status = 'VALIDATED' AND EXISTS (
            SELECT FROM publication.release_evidence WHERE release_id = NEW.release_id))
        OR (OLD.status = 'VALIDATED' AND NEW.status = 'APPROVED' AND EXISTS (
            SELECT FROM publication.release_approval a WHERE a.release_id = NEW.release_id
              AND a.approved_by = NEW.approved_by AND a.approved_at = NEW.approved_at))
        OR (OLD.status = 'APPROVED' AND NEW.status = 'FROZEN'
            AND (OLD.approved_by, OLD.approved_at) = (NEW.approved_by, NEW.approved_at))
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'RELEASE_TRANSITION_INVALID';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION publication.guard_projection() RETURNS trigger
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

CREATE FUNCTION publication.guard_pointer_write() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF current_user <> 'curbos_publication_executor' OR TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'PUBLICATION_POINTER_WORKFLOW_REQUIRED';
    END IF;
    RETURN NEW;
END
$$;
-- +goose StatementEnd

CREATE TRIGGER protect_batch BEFORE UPDATE OR DELETE ON sources.import_batch
FOR EACH ROW EXECUTE FUNCTION publication.guard_batch();
CREATE TRIGGER protect_batch_artifacts BEFORE INSERT OR UPDATE OR DELETE ON sources.import_artifact
FOR EACH ROW EXECUTE FUNCTION publication.guard_artifact_link();
CREATE TRIGGER protect_source_identity BEFORE UPDATE ON sources.source_dataset
FOR EACH ROW EXECUTE FUNCTION publication.guard_dataset_identity();
CREATE TRIGGER protect_raw_artifacts BEFORE UPDATE OR DELETE ON sources.raw_artifact
FOR EACH ROW EXECUTE FUNCTION publication.deny_mutation();
CREATE TRIGGER protect_release BEFORE INSERT OR UPDATE OR DELETE ON sources.dataset_release
FOR EACH ROW EXECUTE FUNCTION publication.guard_release();
CREATE TRIGGER require_pointer_workflow BEFORE INSERT OR UPDATE OR DELETE ON sources.active_release
FOR EACH ROW EXECUTE FUNCTION publication.guard_pointer_write();
CREATE TRIGGER require_event_workflow BEFORE INSERT ON sources.activation_event
FOR EACH ROW EXECUTE FUNCTION publication.guard_pointer_write();

-- +goose StatementBegin
DO $$
DECLARE
    target regclass;
BEGIN
    FOREACH target IN ARRAY ARRAY[
        'geo.release_curb_zone', 'rules.release_policy_definition', 'rules.release_zone_policy_link',
        'sources.release_area', 'sources.release_area_zone', 'sources.qa_issue'
    ]::regclass[] LOOP
        EXECUTE format('CREATE TRIGGER protect_release_projection BEFORE INSERT OR UPDATE OR DELETE ON %s
                        FOR EACH ROW EXECUTE FUNCTION publication.guard_projection()', target);
    END LOOP;
    FOREACH target IN ARRAY ARRAY[
        'publication.release_evidence', 'publication.release_approval', 'sources.activation_event'
    ]::regclass[] LOOP
        EXECUTE format('CREATE TRIGGER protect_publication_evidence BEFORE UPDATE OR DELETE ON %s
                        FOR EACH ROW EXECUTE FUNCTION publication.deny_mutation()', target);
    END LOOP;
    FOREACH target IN ARRAY ARRAY[
        'publication.release_evidence', 'publication.release_approval', 'sources.activation_event',
        'sources.active_release', 'sources.dataset_release', 'sources.qa_issue',
        'geo.release_curb_zone', 'rules.release_policy_definition', 'rules.release_zone_policy_link',
        'sources.release_area', 'sources.release_area_zone', 'sources.source_dataset',
        'sources.raw_artifact', 'sources.import_artifact', 'sources.import_batch'
    ]::regclass[] LOOP
        EXECUTE format('CREATE TRIGGER protect_publication_truncate BEFORE TRUNCATE ON %s
                        FOR EACH STATEMENT EXECUTE FUNCTION publication.deny_mutation()', target);
    END LOOP;
END
$$;

CREATE FUNCTION publication.require_role(capability name) RETURNS void
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NOT pg_has_role(session_user, capability, 'MEMBER') THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'PUBLICATION_ROLE_REQUIRED';
    END IF;
END
$$;

-- Return NULL if the source coordinates cannot round-trip through PostGIS.
CREATE FUNCTION publication.source_geometry(source jsonb, component text) RETURNS public.geometry
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    result public.geometry;
BEGIN
    IF (component = 'zones' AND source->>'type' = 'LineString')
        OR (component = 'areas' AND source->>'type' IN ('Polygon', 'MultiPolygon')) THEN
        result := public.ST_GeomFromGeoJSON(
            jsonb_build_object('type', source->'type', 'coordinates', source->'coordinates'));
        IF public.ST_SRID(result) = 4326 AND public.ST_NDims(result) = 2
           AND NOT public.ST_IsEmpty(result) AND public.ST_IsValid(result, 0)
           AND (public.ST_AsGeoJSON(result, 17, 0)::jsonb->'coordinates') = source->'coordinates' THEN
            RETURN result;
        END IF;
    END IF;
    RETURN NULL;
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
        INSERT INTO publication.release_evidence
            (release_id, candidate_id, report_sha256, plan_sha256, lineage, review_required)
        VALUES (
            p_release, p_candidate, p_report_sha, plan_sha, p_lineage,
            ARRAY(SELECT jsonb_array_elements_text(p_plan->'review_required'))
        );

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
        UPDATE sources.dataset_release SET status = 'VALIDATED' WHERE release_id = p_release;
    END IF;
    RETURN jsonb_build_object(
        'release_id', p_release, 'candidate_report_sha256', p_report_sha,
        'plan_sha256', plan_sha, 'status', (SELECT status FROM sources.dataset_release WHERE release_id = p_release)
    );
END
$$;

-- Independent facts stay separate from the mutable pointer. Enrollment is deliberately
-- unavailable to any publication role, and a real source cannot satisfy the fixture profile.
CREATE FUNCTION publication.check_synthetic_gates(p_release uuid) RETURNS text
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    registered publication.release_evidence%ROWTYPE;
    release_row sources.dataset_release%ROWTYPE;
    source sources.source_dataset%ROWTYPE;
    scope sources.publication_scope%ROWTYPE;
BEGIN
    SELECT * INTO registered FROM publication.release_evidence WHERE release_id = p_release;
    IF NOT FOUND THEN RAISE EXCEPTION 'RELEASE_EVIDENCE_MISSING'; END IF;
    SELECT * INTO release_row FROM sources.dataset_release WHERE release_id = p_release;
    SELECT * INTO source FROM sources.source_dataset
    WHERE dataset_id = (registered.lineage->>'dataset_id')::uuid FOR SHARE;
    IF NOT FOUND OR source.rights_status <> 'APPROVED'
       OR nullif(btrim(source.rights_reference), '') IS NULL THEN
        RAISE EXCEPTION 'SOURCE_RIGHTS_NOT_APPROVED';
    END IF;
    SELECT * INTO scope FROM sources.publication_scope
    WHERE scope_key = release_row.scope_key FOR SHARE;
    IF NOT FOUND OR scope.review_status <> 'APPROVED' OR scope.reviewed_at IS NULL
       OR scope.reviewed_geom IS NULL THEN
        RAISE EXCEPTION 'PUBLICATION_SCOPE_NOT_APPROVED';
    END IF;
    IF source.publisher_key <> 'synthetic-test' OR source.source_profile <> 'synthetic-cds-json'
       OR source.dataset_key !~ '^synthetic-' OR scope.scope_key !~ '^synthetic-'
       OR source.catalog_uri !~ '^https://synthetic-cds[.]invalid/'
       OR NOT EXISTS (
           SELECT FROM publication.synthetic_fixture f
           WHERE (f.batch_id, f.scope_key, f.dataset_id, f.stage_sha256) =
                 (release_row.batch_id, scope.scope_key, source.dataset_id, registered.lineage->>'stage_report_sha256')
       )
       OR EXISTS (
           SELECT FROM sources.import_artifact j JOIN sources.raw_artifact a USING (artifact_id)
           WHERE j.batch_id = release_row.batch_id AND
               coalesce(a.metadata->>'original_source_uri', '') !~ '^https://synthetic-cds[.]invalid/'
       ) THEN
        RAISE EXCEPTION 'REAL_PUBLICATION_DISABLED';
    END IF;
    IF NOT EXISTS (SELECT FROM geo.release_curb_zone WHERE release_id = p_release)
       OR EXISTS (
           SELECT FROM geo.release_curb_zone
           WHERE release_id = p_release AND (
               resource_id IS NOT NULL OR geometry_evidence <> 'SOURCE_REPORTED'
               OR NOT public.ST_CoveredBy(geom, scope.reviewed_geom)
           )
       ) THEN
        RAISE EXCEPTION 'RELEASE_SCOPE_COVERAGE_FAILED';
    END IF;
    RETURN encode(sha256(public.ST_AsEWKB(scope.reviewed_geom, 'XDR')), 'hex');
END
$$;

CREATE FUNCTION publication.approve_release(p_release uuid, p_evidence jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    registered publication.release_evidence%ROWTYPE;
    release_status text;
    scope_digest text;
    key text;
BEGIN
    PERFORM publication.require_role('curbos_publication_reviewer');
    SELECT status INTO release_status FROM sources.dataset_release
    WHERE release_id = p_release FOR UPDATE;
    IF release_status IS DISTINCT FROM 'VALIDATED' THEN
        RAISE EXCEPTION 'RELEASE_NOT_VALIDATED';
    END IF;
    SELECT * INTO STRICT registered FROM publication.release_evidence WHERE release_id = p_release;
    IF registered.registered_by = session_user THEN RAISE EXCEPTION 'INDEPENDENT_REVIEW_REQUIRED'; END IF;
    IF jsonb_typeof(p_evidence) IS DISTINCT FROM 'object'
       OR p_evidence->>'candidate_report_sha256' IS DISTINCT FROM registered.report_sha256
       OR p_evidence->>'plan_sha256' IS DISTINCT FROM registered.plan_sha256 THEN
        RAISE EXCEPTION 'APPROVAL_DIGEST_MISMATCH';
    END IF;
    FOREACH key IN ARRAY ARRAY[
        'qa_ref', 'rights_ref', 'scope_ref', 'coverage_ref', 'placement_ref', 'exclusion_ref'
    ] LOOP
        IF jsonb_typeof(p_evidence->key) IS DISTINCT FROM 'string'
           OR nullif(btrim(p_evidence->>key), '') IS NULL THEN
            RAISE EXCEPTION 'APPROVAL_EVIDENCE_REQUIRED';
        END IF;
    END LOOP;
    IF jsonb_typeof(p_evidence->'review_exclusions') IS DISTINCT FROM 'object'
       OR ARRAY(SELECT jsonb_object_keys(p_evidence->'review_exclusions') ORDER BY 1)
          IS DISTINCT FROM ARRAY(SELECT unnest(registered.review_required) ORDER BY 1)
       OR EXISTS (
           SELECT FROM jsonb_each(p_evidence->'review_exclusions') AS item
           WHERE jsonb_typeof(item.value) <> 'string' OR nullif(btrim(item.value #>> '{}'), '') IS NULL
       ) THEN
        RAISE EXCEPTION 'REVIEW_DISPOSITION_REQUIRED';
    END IF;
    IF jsonb_typeof(p_evidence->'artifact_rights') IS DISTINCT FROM 'object'
       OR ARRAY(SELECT jsonb_object_keys(p_evidence->'artifact_rights') ORDER BY 1)
          IS DISTINCT FROM ARRAY(
             SELECT a.value->>'artifact_id' FROM jsonb_each(registered.lineage->'artifacts') AS a ORDER BY 1
          )
       OR EXISTS (
           SELECT FROM jsonb_each(p_evidence->'artifact_rights') AS item
           WHERE jsonb_typeof(item.value) <> 'string' OR nullif(btrim(item.value #>> '{}'), '') IS NULL
       ) THEN
        RAISE EXCEPTION 'ARTIFACT_RIGHTS_EVIDENCE_REQUIRED';
    END IF;
    scope_digest := publication.check_synthetic_gates(p_release);
    INSERT INTO publication.release_approval (release_id, evidence, reviewed_scope_sha256)
    VALUES (p_release, p_evidence, scope_digest);
    UPDATE sources.dataset_release r SET status = 'APPROVED',
        approved_by = a.approved_by, approved_at = a.approved_at
    FROM publication.release_approval a WHERE r.release_id = p_release AND a.release_id = p_release;
END
$$;

CREATE FUNCTION publication.freeze_release(p_release uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    release_status text;
    reviewed_digest text;
BEGIN
    PERFORM publication.require_role('curbos_publication_reviewer');
    SELECT status INTO release_status FROM sources.dataset_release
    WHERE release_id = p_release FOR UPDATE;
    IF release_status IS DISTINCT FROM 'APPROVED' THEN RAISE EXCEPTION 'RELEASE_NOT_APPROVED'; END IF;
    SELECT reviewed_scope_sha256 INTO reviewed_digest
    FROM publication.release_approval WHERE release_id = p_release;
    IF reviewed_digest IS DISTINCT FROM publication.check_synthetic_gates(p_release) THEN
        RAISE EXCEPTION 'SCOPE_APPROVAL_CHANGED';
    END IF;
    UPDATE sources.dataset_release SET status = 'FROZEN', frozen_at = clock_timestamp()
    WHERE release_id = p_release;
END
$$;
-- +goose StatementEnd

-- +goose StatementBegin
CREATE FUNCTION publication.change_pointer(
    p_scope text, p_target uuid, p_expected bigint, p_action text, p_reason text, p_key text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp SET timezone = 'UTC' AS $$
DECLARE
    event sources.activation_event%ROWTYPE;
    current_id uuid;
    current_version bigint;
    target_status text;
    registrar name;
    reviewer name;
    scope_digest text;
BEGIN
    PERFORM publication.require_role('curbos_publication_operator');
    IF p_scope IS NULL OR p_expected IS NULL OR p_expected < 0
       OR p_action IS NULL OR p_action NOT IN ('ACTIVATE', 'ROLLBACK', 'WITHDRAW')
       OR (p_action = 'WITHDRAW') <> (p_target IS NULL)
       OR p_reason IS NULL OR nullif(btrim(p_reason), '') IS NULL OR length(p_reason) > 2048
       OR p_key IS NULL OR p_key !~ '^[A-Za-z0-9_.:-]{1,128}$' THEN
        RAISE EXCEPTION 'PUBLICATION_REQUEST_INVALID';
    END IF;

    -- Serialize the same key even when callers use different scopes.
    PERFORM pg_advisory_xact_lock(hashtextextended('activation:' || p_key, 304));
    SELECT * INTO event FROM sources.activation_event WHERE idempotency_key = p_key;
    IF FOUND THEN
        IF (event.scope_key, event.to_release_id, event.pointer_version_after - 1,
            event.action, event.reason, event.operator_id)
            IS DISTINCT FROM (p_scope, p_target, p_expected, p_action, p_reason, session_user::text) THEN
            RAISE EXCEPTION USING ERRCODE = '23505', MESSAGE = 'PUBLICATION_IDEMPOTENCY_CONFLICT';
        END IF;
        RETURN to_jsonb(event);
    END IF;

    -- Serialize all pointer requests for this scope, including its first activation.
    PERFORM 1 FROM sources.publication_scope WHERE scope_key = p_scope FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'PUBLICATION_SCOPE_UNKNOWN'; END IF;
    SELECT release_id, pointer_version INTO current_id, current_version
    FROM sources.active_release WHERE scope_key = p_scope;
    current_version := coalesce(current_version, 0);
    IF current_version <> p_expected THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'PUBLICATION_VERSION_CONFLICT';
    END IF;
    IF current_id IS NOT DISTINCT FROM p_target THEN
        RAISE EXCEPTION 'PUBLICATION_POINTER_UNCHANGED';
    END IF;

    IF p_action <> 'WITHDRAW' THEN
        SELECT r.status, e.registered_by, a.approved_by, a.reviewed_scope_sha256
        INTO target_status, registrar, reviewer, scope_digest
        FROM sources.dataset_release r
        LEFT JOIN publication.release_evidence e USING (release_id)
        LEFT JOIN publication.release_approval a USING (release_id)
        WHERE r.release_id = p_target AND r.scope_key = p_scope;
        IF NOT FOUND THEN RAISE EXCEPTION 'PUBLICATION_TARGET_SCOPE_MISMATCH'; END IF;
        IF target_status <> 'FROZEN' THEN RAISE EXCEPTION 'PUBLICATION_TARGET_NOT_FROZEN'; END IF;
        IF registrar IS NULL OR reviewer IS NULL OR registrar = session_user OR reviewer = session_user THEN
            RAISE EXCEPTION 'INDEPENDENT_OPERATOR_REQUIRED';
        END IF;
        IF scope_digest IS DISTINCT FROM publication.check_synthetic_gates(p_target) THEN
            RAISE EXCEPTION 'SCOPE_APPROVAL_CHANGED';
        END IF;
        IF EXISTS (
            SELECT FROM sources.activation_event
            WHERE scope_key = p_scope AND from_release_id = p_target AND action = 'WITHDRAW'
        ) THEN
            RAISE EXCEPTION 'PUBLICATION_TARGET_WITHDRAWN';
        END IF;
        IF p_action = 'ROLLBACK' AND NOT EXISTS (
            SELECT FROM sources.activation_event WHERE scope_key = p_scope AND to_release_id = p_target
        ) THEN
            RAISE EXCEPTION 'ROLLBACK_TARGET_NEVER_ACTIVE';
        END IF;
    END IF;

    INSERT INTO sources.active_release (scope_key, release_id, pointer_version, changed_at)
    VALUES (p_scope, p_target, current_version + 1, clock_timestamp())
    ON CONFLICT (scope_key) DO UPDATE SET
        release_id = excluded.release_id, pointer_version = excluded.pointer_version,
        changed_at = excluded.changed_at
    WHERE sources.active_release.pointer_version = p_expected;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'PUBLICATION_VERSION_CONFLICT';
    END IF;

    INSERT INTO sources.activation_event (
        event_id, scope_key, from_release_id, to_release_id, operator_id,
        reason, action, idempotency_key, pointer_version_after
    )
    VALUES (
        gen_random_uuid(), p_scope, current_id, p_target, session_user,
        p_reason, p_action, p_key, current_version + 1
    ) RETURNING * INTO event;
    RETURN to_jsonb(event);
END
$$;
-- +goose StatementEnd

REVOKE ALL ON SCHEMA publication FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA publication FROM PUBLIC;
REVOKE ALL ON sources.active_release, sources.activation_event, sources.dataset_release,
    sources.qa_issue, geo.release_curb_zone, rules.release_policy_definition,
    rules.release_zone_policy_link, sources.release_area, sources.release_area_zone FROM PUBLIC;

GRANT USAGE ON SCHEMA publication TO curbos_publication_registrar,
    curbos_publication_reviewer, curbos_publication_operator;
GRANT USAGE ON SCHEMA sources TO curbos_publication_registrar;
GRANT SELECT ON sources.import_batch, sources.import_artifact, sources.raw_artifact,
    sources.publication_scope TO curbos_publication_registrar;
GRANT EXECUTE ON FUNCTION publication.source_geometry(jsonb, text),
    publication.register_candidate(uuid, uuid, text, jsonb, jsonb) TO curbos_publication_registrar;
GRANT EXECUTE ON FUNCTION publication.approve_release(uuid, jsonb),
    publication.freeze_release(uuid) TO curbos_publication_reviewer;
GRANT EXECUTE ON FUNCTION publication.change_pointer(text, uuid, bigint, text, text, text)
    TO curbos_publication_operator;
-- No client is a member of the executor role. Only the fixed CAS function runs as it.
GRANT USAGE, CREATE ON SCHEMA publication TO curbos_publication_executor;
ALTER FUNCTION publication.change_pointer(text, uuid, bigint, text, text, text)
    OWNER TO curbos_publication_executor;
REVOKE CREATE ON SCHEMA publication FROM curbos_publication_executor;
GRANT USAGE ON SCHEMA sources, geo TO curbos_publication_executor;
GRANT SELECT ON publication.release_evidence, publication.release_approval,
    publication.synthetic_fixture, sources.source_dataset, sources.publication_scope,
    sources.import_artifact, sources.raw_artifact, sources.dataset_release, geo.release_curb_zone
    TO curbos_publication_executor;
-- PostgreSQL row-locking SELECT requires UPDATE on at least one column.
GRANT UPDATE (rights_status) ON sources.source_dataset TO curbos_publication_executor;
GRANT UPDATE (review_status) ON sources.publication_scope TO curbos_publication_executor;
GRANT SELECT, INSERT, UPDATE ON sources.active_release TO curbos_publication_executor;
GRANT SELECT, INSERT ON sources.activation_event TO curbos_publication_executor;
GRANT EXECUTE ON FUNCTION publication.require_role(name), publication.check_synthetic_gates(uuid)
    TO curbos_publication_executor;

-- +goose Down
-- Never remove guards from a database that has retained publication history.
-- +goose StatementBegin
DO $$
BEGIN
    IF EXISTS (SELECT FROM publication.release_evidence)
       OR EXISTS (SELECT FROM publication.synthetic_fixture)
       OR EXISTS (SELECT FROM sources.activation_event) THEN
        RAISE EXCEPTION 'Publication evidence exists. Dispose only of isolated test databases.';
    END IF;
END
$$;
-- +goose StatementEnd

DROP TRIGGER protect_batch ON sources.import_batch;
DROP TRIGGER protect_batch_artifacts ON sources.import_artifact;
DROP TRIGGER protect_source_identity ON sources.source_dataset;
DROP TRIGGER protect_raw_artifacts ON sources.raw_artifact;
DROP TRIGGER protect_release ON sources.dataset_release;
DROP TRIGGER require_pointer_workflow ON sources.active_release;
DROP TRIGGER require_event_workflow ON sources.activation_event;

DROP TRIGGER protect_release_projection ON geo.release_curb_zone;
DROP TRIGGER protect_release_projection ON rules.release_policy_definition;
DROP TRIGGER protect_release_projection ON rules.release_zone_policy_link;
DROP TRIGGER protect_release_projection ON sources.release_area;
DROP TRIGGER protect_release_projection ON sources.release_area_zone;
DROP TRIGGER protect_release_projection ON sources.qa_issue;
DROP TRIGGER protect_publication_evidence ON sources.activation_event;
DROP TRIGGER protect_publication_truncate ON sources.activation_event;
DROP TRIGGER protect_publication_truncate ON sources.active_release;
DROP TRIGGER protect_publication_truncate ON sources.dataset_release;
DROP TRIGGER protect_publication_truncate ON sources.qa_issue;
DROP TRIGGER protect_publication_truncate ON geo.release_curb_zone;
DROP TRIGGER protect_publication_truncate ON rules.release_policy_definition;
DROP TRIGGER protect_publication_truncate ON rules.release_zone_policy_link;
DROP TRIGGER protect_publication_truncate ON sources.release_area;
DROP TRIGGER protect_publication_truncate ON sources.release_area_zone;
DROP TRIGGER protect_publication_truncate ON sources.source_dataset;
DROP TRIGGER protect_publication_truncate ON sources.raw_artifact;
DROP TRIGGER protect_publication_truncate ON sources.import_artifact;
DROP TRIGGER protect_publication_truncate ON sources.import_batch;
REVOKE SELECT ON sources.import_batch, sources.import_artifact, sources.raw_artifact,
    sources.publication_scope FROM curbos_publication_registrar;
REVOKE USAGE ON SCHEMA sources FROM curbos_publication_registrar;
REVOKE SELECT ON sources.source_dataset, sources.publication_scope, sources.import_artifact,
    sources.raw_artifact, sources.dataset_release, geo.release_curb_zone FROM curbos_publication_executor;
REVOKE UPDATE (rights_status) ON sources.source_dataset FROM curbos_publication_executor;
REVOKE UPDATE (review_status) ON sources.publication_scope FROM curbos_publication_executor;
REVOKE SELECT, INSERT, UPDATE ON sources.active_release FROM curbos_publication_executor;
REVOKE SELECT, INSERT ON sources.activation_event FROM curbos_publication_executor;
REVOKE USAGE ON SCHEMA sources, geo FROM curbos_publication_executor;
-- Capability groups are cluster-wide identities. The migration removes only this database's grants.
DROP SCHEMA publication CASCADE;
