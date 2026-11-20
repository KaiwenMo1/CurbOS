-- Run only in the disposable Compose smoke test. Every row is synthetic.
BEGIN;

-- Verify the migration alone creates no scopes, evidence, resources or pointers.
DO $$
DECLARE
  evidence_table record;
  has_rows boolean;
BEGIN
  FOR evidence_table IN
    SELECT schemaname, tablename FROM pg_catalog.pg_tables
    WHERE schemaname IN ('sources', 'geo', 'rules')
  LOOP
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.%I)', evidence_table.schemaname, evidence_table.tablename)
      INTO has_rows;
    IF has_rows THEN
      RAISE EXCEPTION 'Expected empty table %.%', evidence_table.schemaname, evidence_table.tablename;
    END IF;
  END LOOP;
END;
$$;

CREATE FUNCTION pg_temp.expect_violation(label text, statement text, wanted_state text, wanted_constraint text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  actual_state text;
  actual_constraint text;
BEGIN
  EXECUTE statement;
  RAISE EXCEPTION '% unexpectedly succeeded', label;
EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS actual_state = RETURNED_SQLSTATE, actual_constraint = CONSTRAINT_NAME;
  IF actual_state <> wanted_state OR (wanted_constraint IS NOT NULL AND actual_constraint <> wanted_constraint) THEN
    RAISE EXCEPTION '%: expected % (%), got % (%): %',
      label, wanted_state, wanted_constraint, actual_state, actual_constraint, SQLERRM;
  END IF;
END;
$$;

DO $$
DECLARE
  captured constant timestamptz := '2000-01-01 00:00:00+00';
  digest constant text := repeat('a', 64);
  dataset_a constant uuid := '00000000-0000-4000-8000-000000000101';
  dataset_b constant uuid := '00000000-0000-4000-8000-000000000102';
  artifact_a constant uuid := '00000000-0000-4000-8000-000000000201';
  artifact_b constant uuid := '00000000-0000-4000-8000-000000000202';
  batch_a constant uuid := '00000000-0000-4000-8000-000000000301';
  batch_b constant uuid := '00000000-0000-4000-8000-000000000302';
  batch_a_other constant uuid := '00000000-0000-4000-8000-000000000303';
  batch_unscoped constant uuid := '00000000-0000-4000-8000-000000000304';
  batch_missing constant uuid := '00000000-0000-4000-8000-000000000305';
  release_a constant uuid := '00000000-0000-4000-8000-000000000401';
  release_a_next constant uuid := '00000000-0000-4000-8000-000000000402';
  release_b constant uuid := '00000000-0000-4000-8000-000000000403';
  release_invalid constant uuid := '00000000-0000-4000-8000-000000000404';
  resource constant uuid := '00000000-0000-4000-8000-000000000501';
  qa_invalid constant uuid := '00000000-0000-4000-8000-000000000603';
  line constant public.geometry := public.ST_GeomFromText('LINESTRING(0 0, 1 1)', 4326);
BEGIN
  INSERT INTO sources.publication_scope (scope_key, display_name)
    VALUES ('synthetic-a', 'Synthetic A'), ('synthetic-b', 'Synthetic B');
  INSERT INTO sources.source_dataset (dataset_id, publisher_key, dataset_key, catalog_uri, source_profile)
    VALUES (dataset_a, 'synthetic-publisher-a', 'synthetic-dataset', 'https://a.invalid', 'synthetic'),
           (dataset_b, 'synthetic-publisher-b', 'synthetic-dataset', 'https://b.invalid', 'synthetic');
  INSERT INTO sources.raw_artifact
    (artifact_id, dataset_id, component_role, content_uri, content_sha256, byte_size, retrieved_at, source_format)
    VALUES (artifact_a, dataset_a, 'zones', 'https://a.invalid/zones', digest, 10, captured, 'json'),
           (artifact_b, dataset_b, 'zones', 'https://b.invalid/zones', digest, 10, captured, 'json');

  PERFORM pg_temp.expect_violation('duplicate publisher-scoped dataset',
    format('UPDATE sources.source_dataset SET publisher_key = %L WHERE dataset_id = %L', 'synthetic-publisher-a', dataset_b),
    '23505', 'source_dataset_publisher_key_dataset_key_key');
  PERFORM pg_temp.expect_violation('duplicate dataset-scoped digest',
    format('UPDATE sources.raw_artifact SET dataset_id = %L WHERE artifact_id = %L', dataset_a, artifact_b),
    '23505', 'raw_artifact_dataset_id_content_sha256_key');
  PERFORM pg_temp.expect_violation('non-hex digest',
    format('UPDATE sources.raw_artifact SET content_sha256 = %L WHERE artifact_id = %L', repeat('g', 64), artifact_a),
    '23514', 'raw_artifact_content_sha256_check');
  PERFORM pg_temp.expect_violation('digest with a trailing space',
    format('UPDATE sources.raw_artifact SET content_sha256 = %L WHERE artifact_id = %L', digest || ' ', artifact_a),
    '23514', 'raw_artifact_content_sha256_check');
  PERFORM pg_temp.expect_violation('array in artifact metadata',
    format('UPDATE sources.raw_artifact SET metadata = %L WHERE artifact_id = %L', '[]', artifact_a),
    '23514', 'raw_artifact_metadata_check');

  INSERT INTO sources.import_batch (batch_id, scope_key, adapter_version, source_profile_version, capture_manifest_sha256)
    VALUES (batch_a, 'synthetic-a', 'synthetic-v1', 'synthetic-v1', digest),
           (batch_b, 'synthetic-b', 'synthetic-v1', 'synthetic-v1', digest),
           (batch_a_other, 'synthetic-a', 'synthetic-v1', 'synthetic-v1', digest),
           (batch_unscoped, NULL, 'synthetic-v1', 'synthetic-v1', digest);
  INSERT INTO sources.import_artifact (batch_id, component_role, artifact_id)
    VALUES (batch_a, 'zones', artifact_a), (batch_b, 'zones', artifact_b);
  INSERT INTO sources.dataset_release (release_id, batch_id, scope_key)
    VALUES (release_a, batch_a, 'synthetic-a'), (release_a_next, batch_a, 'synthetic-a'),
           (release_b, batch_b, 'synthetic-b');

  PERFORM pg_temp.expect_violation('release referencing batch in another scope',
    format('INSERT INTO sources.dataset_release (release_id, batch_id, scope_key) VALUES (%L, %L, %L)',
      release_invalid, batch_b, 'synthetic-a'),
    '23503', 'dataset_release_batch_scope_fk');
  PERFORM pg_temp.expect_violation('release referencing an unscoped batch',
    format('INSERT INTO sources.dataset_release (release_id, batch_id, scope_key) VALUES (%L, %L, %L)',
      release_invalid, batch_unscoped, 'synthetic-a'),
    '23503', 'dataset_release_batch_scope_fk');
  PERFORM pg_temp.expect_violation('clearing scope on a batch with releases',
    format('UPDATE sources.import_batch SET scope_key = NULL WHERE batch_id = %L', batch_a),
    '23503', 'dataset_release_batch_scope_fk');

  INSERT INTO sources.qa_issue (qa_id, batch_id, release_id, source_object_type, issue_code, severity, disposition)
    VALUES ('00000000-0000-4000-8000-000000000601', batch_a, release_a, 'ZONE', 'SYNTHETIC_QA', 'INFO', 'RECORDED'),
           ('00000000-0000-4000-8000-000000000602', batch_unscoped, NULL, 'BATCH', 'SYNTHETIC_QA', 'INFO', 'RECORDED');
  PERFORM pg_temp.expect_violation('QA linking a release from another batch in the same scope',
    format('INSERT INTO sources.qa_issue
            (qa_id, batch_id, release_id, source_object_type, issue_code, severity, disposition)
            VALUES (%L, %L, %L, %L, %L, %L, %L)',
      qa_invalid, batch_a_other, release_a, 'ZONE', 'SYNTHETIC_QA', 'INFO', 'RECORDED'),
    '23503', 'qa_issue_batch_release_fk');
  PERFORM pg_temp.expect_violation('batch-only QA referencing a missing batch',
    format('INSERT INTO sources.qa_issue (qa_id, batch_id, source_object_type, issue_code, severity, disposition)
            VALUES (%L, %L, %L, %L, %L, %L)',
      qa_invalid, batch_missing, 'BATCH', 'SYNTHETIC_QA', 'INFO', 'RECORDED'),
    '23503', 'qa_issue_batch_id_fkey');
  PERFORM pg_temp.expect_violation('moving a release with QA to another batch in the same scope',
    format('UPDATE sources.dataset_release SET batch_id = %L WHERE release_id = %L', batch_a_other, release_a),
    '23503', 'qa_issue_batch_release_fk');

  IF EXISTS (SELECT 1 FROM sources.dataset_release WHERE status <> 'CANDIDATE')
    OR EXISTS (SELECT 1 FROM sources.active_release) THEN
    RAISE EXCEPTION 'New candidate releases must start inactive';
  END IF;
  PERFORM pg_temp.expect_violation('freeze without approval metadata',
    format('UPDATE sources.dataset_release SET status = %L WHERE release_id = %L', 'FROZEN', release_a),
    '23514', 'dataset_release_frozen_metadata_check');
  PERFORM pg_temp.expect_violation('short validation digest',
    format('UPDATE sources.dataset_release SET validation_report_sha256 = %L WHERE release_id = %L', 'aa', release_a),
    '23514', 'dataset_release_validation_report_sha256_check');
  PERFORM pg_temp.expect_violation('array in exclusion summary',
    format('UPDATE sources.dataset_release SET exclusion_summary = %L WHERE release_id = %L', '[]', release_a),
    '23514', 'dataset_release_exclusion_summary_check');

  -- The same source identifiers can appear in distinct releases.
  INSERT INTO geo.release_curb_zone (release_id, source_zone_id, raw_artifact_id, geom, geometry_sha256)
    VALUES (release_a, 'synthetic-zone', artifact_a, line, digest),
           (release_a_next, 'synthetic-zone', artifact_a, line, digest),
           (release_a_next, 'synthetic-next-zone', artifact_a, line, digest);
  INSERT INTO rules.release_policy_definition (release_id, source_policy_id, source_jsonb)
    VALUES (release_a, 'synthetic-policy', '{}'), (release_a_next, 'synthetic-policy', '{}'),
           (release_a_next, 'synthetic-next-policy', '{}');
  INSERT INTO sources.release_area (release_id, source_area_id, raw_artifact_id)
    VALUES (release_a, 'synthetic-area', artifact_a), (release_a_next, 'synthetic-area', artifact_a),
           (release_a_next, 'synthetic-next-area', artifact_a);
  INSERT INTO rules.release_zone_policy_link (release_id, source_zone_id, source_policy_id, source_position)
    VALUES (release_a, 'synthetic-zone', 'synthetic-policy', 0),
           (release_a_next, 'synthetic-next-zone', 'synthetic-next-policy', 0);
  INSERT INTO sources.release_area_zone (release_id, source_area_id, source_zone_id)
    VALUES (release_a, 'synthetic-area', 'synthetic-zone'),
           (release_a_next, 'synthetic-next-area', 'synthetic-next-zone');

  PERFORM pg_temp.expect_violation('duplicate zone in one release',
    format('INSERT INTO geo.release_curb_zone SELECT * FROM geo.release_curb_zone WHERE release_id = %L', release_a),
    '23505', 'release_curb_zone_pkey');
  PERFORM pg_temp.expect_violation('duplicate policy in one release',
    format('INSERT INTO rules.release_policy_definition VALUES (%L, %L, %L)', release_a, 'synthetic-policy', '{}'),
    '23505', 'release_policy_definition_pkey');
  PERFORM pg_temp.expect_violation('duplicate area in one release',
    format('INSERT INTO sources.release_area (release_id, source_area_id, raw_artifact_id) VALUES (%L, %L, %L)',
      release_a, 'synthetic-area', artifact_a),
    '23505', 'release_area_pkey');

  PERFORM pg_temp.expect_violation('missing policy',
    format('INSERT INTO rules.release_zone_policy_link VALUES (%L, %L, %L, 1)', release_a, 'synthetic-zone', 'synthetic-missing'),
    '23503', 'release_zone_policy_link_policy_fk');
  PERFORM pg_temp.expect_violation('policy from another release in the same scope',
    format('INSERT INTO rules.release_zone_policy_link VALUES (%L, %L, %L, 1)', release_a, 'synthetic-zone', 'synthetic-next-policy'),
    '23503', 'release_zone_policy_link_policy_fk');
  PERFORM pg_temp.expect_violation('policy link to zone in another release',
    format('INSERT INTO rules.release_zone_policy_link VALUES (%L, %L, %L, 0)', release_a, 'synthetic-next-zone', 'synthetic-policy'),
    '23503', 'release_zone_policy_link_zone_fk');
  PERFORM pg_temp.expect_violation('missing area',
    format('INSERT INTO sources.release_area_zone VALUES (%L, %L, %L)', release_a, 'synthetic-missing', 'synthetic-zone'),
    '23503', 'release_area_zone_area_fk');
  PERFORM pg_temp.expect_violation('missing area member',
    format('INSERT INTO sources.release_area_zone VALUES (%L, %L, %L)', release_a, 'synthetic-area', 'synthetic-missing'),
    '23503', 'release_area_zone_zone_fk');
  PERFORM pg_temp.expect_violation('area from another release in the same scope',
    format('INSERT INTO sources.release_area_zone VALUES (%L, %L, %L)', release_a, 'synthetic-next-area', 'synthetic-zone'),
    '23503', 'release_area_zone_area_fk');
  PERFORM pg_temp.expect_violation('area member from another release in the same scope',
    format('INSERT INTO sources.release_area_zone VALUES (%L, %L, %L)', release_a, 'synthetic-area', 'synthetic-next-zone'),
    '23503', 'release_area_zone_zone_fk');

  PERFORM pg_temp.expect_violation('empty line',
    format('UPDATE geo.release_curb_zone SET geom = public.ST_GeomFromText(%L, 4326) WHERE release_id = %L',
      'LINESTRING EMPTY', release_a),
    '23514', 'release_curb_zone_geom_check');
  PERFORM pg_temp.expect_violation('invalid line with coincident vertices',
    format('UPDATE geo.release_curb_zone SET geom = public.ST_GeomFromText(%L, 4326) WHERE release_id = %L',
      'LINESTRING(0 0, 0 0)', release_a),
    '23514', 'release_curb_zone_geom_check');
  PERFORM pg_temp.expect_violation('wrong SRID',
    format('UPDATE geo.release_curb_zone SET geom = public.ST_GeomFromText(%L, 3857) WHERE release_id = %L',
      'LINESTRING(0 0, 1 1)', release_a),
    '22023');
  PERFORM pg_temp.expect_violation('wrong geometry type',
    format('UPDATE geo.release_curb_zone SET geom = public.ST_GeomFromText(%L, 4326) WHERE release_id = %L',
      'POINT(0 0)', release_a),
    '22023');

  IF EXISTS (SELECT 1 FROM geo.parking_resource) OR EXISTS (SELECT 1 FROM geo.source_resource_link)
    OR EXISTS (SELECT 1 FROM geo.release_curb_zone WHERE resource_id IS NOT NULL) THEN
    RAISE EXCEPTION 'Zone projection must leave physical identity unassigned';
  END IF;
  INSERT INTO geo.parking_resource (resource_id, subtype) VALUES (resource, 'CURB_ZONE');
  INSERT INTO geo.source_resource_link
    (resource_id, dataset_id, source_object_type, source_object_id, link_revision, evidence_ref, decision_method)
    VALUES (resource, dataset_a, 'ZONE', 'synthetic-zone', 1, 'synthetic-review-a', 'synthetic-review'),
           (resource, dataset_b, 'ZONE', 'synthetic-zone', 1, 'synthetic-review-b', 'synthetic-review');
  PERFORM pg_temp.expect_violation('duplicate dataset-scoped source identity revision',
    format('UPDATE geo.source_resource_link SET dataset_id = %L WHERE dataset_id = %L', dataset_a, dataset_b),
    '23505', 'source_resource_link_pkey');

  -- Test the pointer's shape entirely inside this rollback-only synthetic transaction.
  UPDATE sources.dataset_release
    SET status = 'FROZEN', approved_by = 'synthetic-reviewer',
        approved_at = captured, frozen_at = captured, validation_report_sha256 = digest
    WHERE release_id IN (release_a, release_b);
  INSERT INTO sources.active_release (scope_key) VALUES ('synthetic-a');
  IF NOT EXISTS (SELECT 1 FROM sources.active_release
                 WHERE scope_key = 'synthetic-a' AND release_id IS NULL AND pointer_version = 0) THEN
    RAISE EXCEPTION 'A new pointer must default to no release';
  END IF;
  PERFORM pg_temp.expect_violation('pointer to frozen release in another scope',
    format('UPDATE sources.active_release SET release_id = %L WHERE scope_key = %L', release_b, 'synthetic-a'),
    '23503', 'active_release_scope_fk');
  UPDATE sources.active_release SET release_id = release_a WHERE scope_key = 'synthetic-a';
  IF NOT EXISTS (SELECT 1 FROM sources.active_release
                 WHERE scope_key = 'synthetic-a' AND release_id = release_a) THEN
    RAISE EXCEPTION 'Expected a same-scope pointer';
  END IF;
END;
$$;

ROLLBACK;
