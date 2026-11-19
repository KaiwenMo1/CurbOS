-- +goose Up
CREATE EXTENSION postgis WITH SCHEMA public;

-- +goose Down
DROP EXTENSION postgis;
