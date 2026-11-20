-- +goose Up
-- M2 Master Pack v1.0, Session 16 candidate with exact digest and JSON object checks.
-- This schema records evidence and release relationships. It creates no active pointers.
-- Controlled activation, source bundle validation and immutability are later gates.

CREATE SCHEMA sources;
CREATE SCHEMA geo;
CREATE SCHEMA rules;

CREATE TABLE sources.publication_scope (
  scope_key text PRIMARY KEY,
  display_name text NOT NULL,
  reviewed_geom public.geometry(MultiPolygon, 4326),
  review_status text NOT NULL DEFAULT 'UNREVIEWED'
    CHECK (review_status IN ('UNREVIEWED', 'UNDER_REVIEW', 'APPROVED', 'WITHDRAWN')),
  reviewed_at timestamptz,
  CHECK (reviewed_geom IS NULL OR (NOT public.ST_IsEmpty(reviewed_geom) AND public.ST_IsValid(reviewed_geom)))
);

CREATE TABLE sources.source_dataset (
  dataset_id uuid PRIMARY KEY,
  publisher_key text NOT NULL,
  dataset_key text NOT NULL,
  catalog_uri text NOT NULL,
  source_profile text NOT NULL,
  rights_status text NOT NULL DEFAULT 'UNKNOWN'
    CHECK (rights_status IN ('UNKNOWN', 'REVIEW_REQUIRED', 'APPROVED', 'DENIED', 'WITHDRAWN')),
  rights_reference text,
  UNIQUE (publisher_key, dataset_key)
);

CREATE TABLE sources.raw_artifact (
  artifact_id uuid PRIMARY KEY,
  dataset_id uuid NOT NULL REFERENCES sources.source_dataset(dataset_id) ON DELETE RESTRICT,
  component_role text NOT NULL,
  content_uri text NOT NULL,
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size bigint NOT NULL CHECK (byte_size >= 0),
  retrieved_at timestamptz NOT NULL,
  source_as_of timestamptz,
  source_format text NOT NULL,
  source_crs text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  UNIQUE (dataset_id, content_sha256)
);

CREATE TABLE sources.import_batch (
  batch_id uuid PRIMARY KEY,
  scope_key text REFERENCES sources.publication_scope(scope_key),
  adapter_version text NOT NULL,
  source_profile_version text NOT NULL,
  capture_manifest_sha256 text NOT NULL CHECK (capture_manifest_sha256 ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'CAPTURED'
    CHECK (status IN ('CAPTURED', 'STAGED', 'VALIDATED', 'REJECTED')),
  validation_report_sha256 text CHECK (validation_report_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sources.import_artifact (
  batch_id uuid NOT NULL REFERENCES sources.import_batch(batch_id) ON DELETE RESTRICT,
  component_role text NOT NULL,
  artifact_id uuid NOT NULL REFERENCES sources.raw_artifact(artifact_id) ON DELETE RESTRICT,
  PRIMARY KEY (batch_id, component_role, artifact_id)
);

CREATE TABLE sources.dataset_release (
  release_id uuid PRIMARY KEY,
  batch_id uuid NOT NULL REFERENCES sources.import_batch(batch_id) ON DELETE RESTRICT,
  scope_key text NOT NULL REFERENCES sources.publication_scope(scope_key) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'CANDIDATE'
    CHECK (status IN ('CANDIDATE', 'VALIDATED', 'APPROVED', 'FROZEN', 'REJECTED')),
  validation_report_sha256 text CHECK (validation_report_sha256 ~ '^[0-9a-f]{64}$'),
  approved_by text,
  approved_at timestamptz,
  frozen_at timestamptz,
  source_as_of timestamptz,
  exclusion_summary jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(exclusion_summary) = 'object'),
  UNIQUE (scope_key, release_id),
  CONSTRAINT dataset_release_frozen_metadata_check CHECK (
    status <> 'FROZEN' OR (
      frozen_at IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL
      AND validation_report_sha256 IS NOT NULL
    )
  )
);

CREATE TABLE geo.parking_resource (
  resource_id uuid PRIMARY KEY,
  subtype text NOT NULL CHECK (subtype IN ('CURB_ZONE', 'PARKING_SPACE', 'PARKING_FACILITY')),
  identity_status text NOT NULL DEFAULT 'UNREVIEWED',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE geo.source_resource_link (
  resource_id uuid NOT NULL REFERENCES geo.parking_resource(resource_id) ON DELETE RESTRICT,
  dataset_id uuid NOT NULL REFERENCES sources.source_dataset(dataset_id) ON DELETE RESTRICT,
  source_object_type text NOT NULL,
  source_object_id text NOT NULL,
  link_revision integer NOT NULL CHECK (link_revision >= 1),
  evidence_ref text NOT NULL,
  decision_method text NOT NULL,
  PRIMARY KEY (dataset_id, source_object_type, source_object_id, link_revision)
);

CREATE TABLE geo.release_curb_zone (
  release_id uuid NOT NULL REFERENCES sources.dataset_release(release_id) ON DELETE RESTRICT,
  source_zone_id text NOT NULL,
  raw_artifact_id uuid NOT NULL REFERENCES sources.raw_artifact(artifact_id) ON DELETE RESTRICT,
  source_crs text,
  geom public.geometry(LineString, 4326) NOT NULL,
  geometry_sha256 text NOT NULL CHECK (geometry_sha256 ~ '^[0-9a-f]{64}$'),
  street_side text CHECK (street_side IN ('LEFT', 'RIGHT', 'UNKNOWN')),
  road_reference text,
  geometry_evidence text NOT NULL DEFAULT 'SOURCE_REPORTED'
    CHECK (geometry_evidence IN ('SOURCE_REPORTED', 'APPROXIMATE_ALIGNED', 'INDEPENDENTLY_REVIEWED', 'EXCLUDED')),
  policy_ref_status text NOT NULL DEFAULT 'UNASSESSED'
    CHECK (policy_ref_status IN ('UNASSESSED', 'COMPLETE', 'INCOMPLETE')),
  source_num_spaces integer,
  resource_id uuid REFERENCES geo.parking_resource(resource_id) ON DELETE RESTRICT,
  PRIMARY KEY (release_id, source_zone_id),
  CONSTRAINT release_curb_zone_geom_check
    CHECK (NOT public.ST_IsEmpty(geom) AND public.ST_IsValid(geom))
);
CREATE INDEX release_curb_zone_geom_gix ON geo.release_curb_zone USING gist (geom);

CREATE TABLE rules.release_policy_definition (
  release_id uuid NOT NULL REFERENCES sources.dataset_release(release_id) ON DELETE RESTRICT,
  source_policy_id text NOT NULL,
  source_jsonb jsonb NOT NULL,
  parse_status text NOT NULL DEFAULT 'UNASSESSED',
  PRIMARY KEY (release_id, source_policy_id)
);

CREATE TABLE rules.release_zone_policy_link (
  release_id uuid NOT NULL,
  source_zone_id text NOT NULL,
  source_policy_id text NOT NULL,
  source_position integer NOT NULL CHECK (source_position >= 0),
  PRIMARY KEY (release_id, source_zone_id, source_policy_id, source_position),
  CONSTRAINT release_zone_policy_link_zone_fk
    FOREIGN KEY (release_id, source_zone_id) REFERENCES geo.release_curb_zone(release_id, source_zone_id) ON DELETE RESTRICT,
  CONSTRAINT release_zone_policy_link_policy_fk
    FOREIGN KEY (release_id, source_policy_id) REFERENCES rules.release_policy_definition(release_id, source_policy_id) ON DELETE RESTRICT
);

CREATE TABLE sources.release_area (
  release_id uuid NOT NULL REFERENCES sources.dataset_release(release_id) ON DELETE RESTRICT,
  source_area_id text NOT NULL,
  name text,
  description text,
  raw_artifact_id uuid NOT NULL REFERENCES sources.raw_artifact(artifact_id) ON DELETE RESTRICT,
  source_geometry_type text,
  display_geom public.geometry(Geometry, 4326),
  geometry_qa_code text,
  PRIMARY KEY (release_id, source_area_id)
);

CREATE TABLE sources.release_area_zone (
  release_id uuid NOT NULL,
  source_area_id text NOT NULL,
  source_zone_id text NOT NULL,
  PRIMARY KEY (release_id, source_area_id, source_zone_id),
  CONSTRAINT release_area_zone_area_fk
    FOREIGN KEY (release_id, source_area_id) REFERENCES sources.release_area(release_id, source_area_id) ON DELETE RESTRICT,
  CONSTRAINT release_area_zone_zone_fk
    FOREIGN KEY (release_id, source_zone_id) REFERENCES geo.release_curb_zone(release_id, source_zone_id) ON DELETE RESTRICT
);

CREATE TABLE sources.qa_issue (
  qa_id uuid PRIMARY KEY,
  batch_id uuid NOT NULL REFERENCES sources.import_batch(batch_id) ON DELETE RESTRICT,
  release_id uuid REFERENCES sources.dataset_release(release_id) ON DELETE RESTRICT,
  source_object_type text NOT NULL,
  source_object_id text,
  issue_code text NOT NULL,
  severity text NOT NULL,
  disposition text NOT NULL,
  evidence_ref text,
  observed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sources.active_release (
  scope_key text PRIMARY KEY REFERENCES sources.publication_scope(scope_key) ON DELETE RESTRICT,
  release_id uuid,
  pointer_version bigint NOT NULL DEFAULT 0 CHECK (pointer_version >= 0),
  changed_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT active_release_scope_fk
    FOREIGN KEY (scope_key, release_id) REFERENCES sources.dataset_release(scope_key, release_id) ON DELETE RESTRICT
);

CREATE TABLE sources.activation_event (
  event_id uuid PRIMARY KEY,
  scope_key text NOT NULL REFERENCES sources.publication_scope(scope_key) ON DELETE RESTRICT,
  from_release_id uuid,
  to_release_id uuid,
  operator_id text NOT NULL,
  reason text NOT NULL,
  action text NOT NULL CHECK (action IN ('ACTIVATE', 'ROLLBACK', 'WITHDRAW')),
  idempotency_key text NOT NULL UNIQUE,
  pointer_version_after bigint NOT NULL,
  happened_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (scope_key, from_release_id) REFERENCES sources.dataset_release(scope_key, release_id) ON DELETE RESTRICT,
  FOREIGN KEY (scope_key, to_release_id) REFERENCES sources.dataset_release(scope_key, release_id) ON DELETE RESTRICT
);

-- +goose Down
-- Destructive schema rollback for disposable tests. Keep the M1 PostGIS extension.
DROP TABLE sources.activation_event;
DROP TABLE sources.active_release;
DROP TABLE sources.qa_issue;
DROP TABLE sources.release_area_zone;
DROP TABLE sources.release_area;
DROP TABLE rules.release_zone_policy_link;
DROP TABLE rules.release_policy_definition;
DROP TABLE geo.release_curb_zone;
DROP TABLE geo.source_resource_link;
DROP TABLE geo.parking_resource;
DROP TABLE sources.dataset_release;
DROP TABLE sources.import_artifact;
DROP TABLE sources.import_batch;
DROP TABLE sources.raw_artifact;
DROP TABLE sources.source_dataset;
DROP TABLE sources.publication_scope;

DROP SCHEMA rules;
DROP SCHEMA geo;
DROP SCHEMA sources;
