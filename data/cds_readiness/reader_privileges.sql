-- Run with psql -v reader=<already provisioned private assessment login>.
GRANT USAGE ON SCHEMA sources, publication TO :"reader";
GRANT SELECT (batch_id, scope_key, status, capture_manifest_sha256, validation_report_sha256,
    adapter_version, source_profile_version) ON sources.import_batch TO :"reader";
GRANT SELECT (batch_id, component_role, artifact_id) ON sources.import_artifact TO :"reader";
GRANT SELECT (artifact_id, dataset_id, component_role, content_sha256, byte_size, content_uri,
    source_format, retrieved_at, source_as_of, metadata) ON sources.raw_artifact TO :"reader";
GRANT SELECT (dataset_id, publisher_key, dataset_key, source_profile, catalog_uri, rights_status,
    rights_reference) ON sources.source_dataset TO :"reader";
GRANT SELECT (scope_key, reviewed_geom, review_status, reviewed_at)
    ON sources.publication_scope TO :"reader";
GRANT SELECT (release_id, batch_id, scope_key, status, validation_report_sha256)
    ON sources.dataset_release TO :"reader";
GRANT SELECT (release_id, candidate_id, report_sha256, plan_sha256, lineage, review_required)
    ON publication.release_evidence TO :"reader";
GRANT SELECT (release_id) ON publication.release_verification, publication.release_approval TO :"reader";
GRANT SELECT (scope_key, release_id) ON sources.active_release TO :"reader";
GRANT EXECUTE ON FUNCTION publication.source_geometry(jsonb, text) TO :"reader";
