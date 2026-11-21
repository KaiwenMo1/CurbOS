-- +goose Up
ALTER FUNCTION discovery.read_synthetic(text, uuid, double precision[], text, integer, text)
    RENAME TO read_synthetic_v5;
REVOKE EXECUTE ON FUNCTION discovery.read_synthetic_v5(text, uuid, double precision[], text, integer, text)
    FROM curbos_api_synthetic_reader;

-- +goose StatementBegin
CREATE FUNCTION discovery.read_synthetic(
    p_scope text, p_pin uuid, p_bbox double precision[], p_after text, p_limit integer, p_zone text
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    -- PR-04 commits a scope withdrawal event and clears the pointer atomically.
    -- Only a later audited selection of this specific release can reopen its pin.
    -- Missing activation history falls through to the existing same-scope 404 checks.
    IF p_pin IS NOT NULL AND (
        SELECT max(pointer_version_after) FROM sources.activation_event
        WHERE scope_key = p_scope AND to_release_id = p_pin
    ) < (
        SELECT max(pointer_version_after) FROM sources.activation_event
        WHERE scope_key = p_scope AND action = 'WITHDRAW'
    ) THEN
        RETURN jsonb_build_object('error_code', 'RELEASE_WITHDRAWN');
    END IF;

    -- The guarded read and the original projection use the same statement snapshot.
    RETURN discovery.read_synthetic_v5(p_scope, p_pin, p_bbox, p_after, p_limit, p_zone);
END
$$;
-- +goose StatementEnd

REVOKE EXECUTE ON FUNCTION discovery.read_synthetic(text, uuid, double precision[], text, integer, text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION discovery.read_synthetic(text, uuid, double precision[], text, integer, text)
    TO curbos_api_synthetic_reader;

-- +goose Down
DROP FUNCTION discovery.read_synthetic(text, uuid, double precision[], text, integer, text);
ALTER FUNCTION discovery.read_synthetic_v5(text, uuid, double precision[], text, integer, text)
    RENAME TO read_synthetic;
GRANT EXECUTE ON FUNCTION discovery.read_synthetic(text, uuid, double precision[], text, integer, text)
    TO curbos_api_synthetic_reader;
