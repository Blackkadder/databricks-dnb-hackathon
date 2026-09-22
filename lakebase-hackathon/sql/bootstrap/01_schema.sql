-- Copyright 2026 Databricks, Inc.
-- SPDX-License-Identifier: Apache-2.0
--
-- Bootstrap schema for the nyc_taxi dataset: a dedicated `cabs` schema holding the
-- stock PostGIS extension plus a 5-table star schema (with foreign keys and GIST
-- spatial indexes). Run against the nyc_taxi database; the database itself is created
-- (idempotently) by the caller.
-- Idempotent: safe to re-run (CREATE ... IF NOT EXISTS throughout).
--
-- Application tables live in the `cabs` schema (not `public`). We set the search_path
-- at the DATABASE level so every future connection — notebook cells, psql, pyway, and
-- any branch cloned from this database — resolves unqualified names like `trips` to
-- `cabs.trips` automatically. PostGIS itself stays in `public` (shared, standard).

CREATE SCHEMA IF NOT EXISTS cabs;

-- PostGIS installs into `public` (the search_path default right now), so its types and
-- functions stay shared and standard.
CREATE EXTENSION IF NOT EXISTS postgis;

-- Persist the search path for ALL future sessions on this database (and every branch
-- cloned from it), then set it for THIS bootstrap session so the tables below land in
-- `cabs`. `cabs` is searched first; `public` still resolves PostGIS types/functions.
ALTER DATABASE nyc_taxi SET search_path = cabs, public;
SET search_path = cabs, public;

CREATE TABLE IF NOT EXISTS taxi_zones (
    location_id   INT PRIMARY KEY,
    borough       TEXT NOT NULL,
    zone          TEXT NOT NULL,
    service_zone  TEXT,
    geom          geometry(MultiPolygon, 4326)
);
CREATE INDEX IF NOT EXISTS idx_taxi_zones_geom ON taxi_zones USING GIST (geom);

CREATE TABLE IF NOT EXISTS vendors (vendor_id INT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rate_codes (rate_code_id INT PRIMARY KEY, description TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payment_types (payment_type INT PRIMARY KEY, description TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS trips (
    trip_id             BIGSERIAL PRIMARY KEY,
    vendor_id           INT REFERENCES vendors(vendor_id),
    pickup_datetime     TIMESTAMPTZ NOT NULL,
    dropoff_datetime    TIMESTAMPTZ NOT NULL,
    passenger_count     SMALLINT,
    trip_distance       NUMERIC(8,2),
    pickup_location_id  INT REFERENCES taxi_zones(location_id),
    dropoff_location_id INT REFERENCES taxi_zones(location_id),
    rate_code_id        INT REFERENCES rate_codes(rate_code_id),
    payment_type        INT REFERENCES payment_types(payment_type),
    fare_amount         NUMERIC(8,2),
    tip_amount          NUMERIC(8,2),
    total_amount        NUMERIC(8,2),
    pickup_point        geometry(Point, 4326),
    dropoff_point       geometry(Point, 4326)
);
CREATE INDEX IF NOT EXISTS idx_trips_pickup_point  ON trips USING GIST (pickup_point);
CREATE INDEX IF NOT EXISTS idx_trips_dropoff_point ON trips USING GIST (dropoff_point);
CREATE INDEX IF NOT EXISTS idx_trips_pickup_dt     ON trips (pickup_datetime);
