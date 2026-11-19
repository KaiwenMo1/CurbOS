package postgres

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5/pgxpool"
)

// CheckReady tests the currently deployed M1 database baseline in one round trip.
// The caller supplies the deadline for both acquiring a connection and querying.
func CheckReady(ctx context.Context, pool *pgxpool.Pool) error {
	const query = `
		SELECT public.postgis_lib_version() IS NOT NULL
			AND EXISTS (SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'postgis')
			AND COALESCE((
				SELECT is_applied
				FROM public.goose_db_version
				WHERE version_id = 1
				ORDER BY id DESC
				LIMIT 1
			), false)`
	var ready bool
	if err := pool.QueryRow(ctx, query).Scan(&ready); err != nil {
		return err
	}
	if !ready {
		return errors.New("required database baseline is missing")
	}
	return nil
}
