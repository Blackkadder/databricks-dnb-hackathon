-- Copyright 2026 Databricks, Inc.
-- SPDX-License-Identifier: Apache-2.0
--
-- Seed data for the nyc_taxi dataset: lookup dimensions, a few TLC zones, and sample
-- trips. Run against the nyc_taxi database after 01_schema.sql.
-- Deterministic + re-runnable: lookups/zones upsert; trips are reset then loaded.

-- Application tables live in the `cabs` schema (see 01_schema.sql). Set it explicitly
-- so this file also resolves the right tables when run on its own in a fresh session.
SET search_path = cabs, public;

INSERT INTO vendors (vendor_id, name) VALUES
    (1,'Creative Mobile Technologies'),(2,'VeriFone Inc.') ON CONFLICT (vendor_id) DO NOTHING;

INSERT INTO rate_codes (rate_code_id, description) VALUES
    (1,'Standard rate'),(2,'JFK'),(3,'Newark'),(4,'Nassau or Westchester'),
    (5,'Negotiated fare'),(6,'Group ride') ON CONFLICT (rate_code_id) DO NOTHING;

INSERT INTO payment_types (payment_type, description) VALUES
    (1,'Credit card'),(2,'Cash'),(3,'No charge'),(4,'Dispute'),(5,'Unknown'),
    (6,'Voided trip') ON CONFLICT (payment_type) DO NOTHING;

INSERT INTO taxi_zones (location_id, borough, zone, service_zone, geom) VALUES
    (132,'Queens','JFK Airport','Airports',
     ST_Multi(ST_GeomFromText('POLYGON((-73.79 40.64,-73.77 40.64,-73.77 40.66,-73.79 40.66,-73.79 40.64))',4326))),
    (161,'Manhattan','Midtown Center','Yellow Zone',
     ST_Multi(ST_GeomFromText('POLYGON((-73.98 40.75,-73.97 40.75,-73.97 40.76,-73.98 40.76,-73.98 40.75))',4326))),
    (230,'Manhattan','Times Sq/Theatre District','Yellow Zone',
     ST_Multi(ST_GeomFromText('POLYGON((-73.99 40.75,-73.98 40.75,-73.98 40.76,-73.99 40.76,-73.99 40.75))',4326)))
ON CONFLICT (location_id) DO NOTHING;

TRUNCATE trips RESTART IDENTITY;
INSERT INTO trips (vendor_id, pickup_datetime, dropoff_datetime, passenger_count,
                   trip_distance, pickup_location_id, dropoff_location_id,
                   rate_code_id, payment_type, fare_amount, tip_amount, total_amount,
                   pickup_point, dropoff_point) VALUES
    (2,'2026-08-01 08:12:00+00','2026-08-01 08:47:00+00',1,17.6,132,161,2,1,70.00,14.00,88.80,
     ST_SetSRID(ST_MakePoint(-73.7810,40.6440),4326),ST_SetSRID(ST_MakePoint(-73.9760,40.7555),4326)),
    (1,'2026-08-01 09:05:00+00','2026-08-01 09:14:00+00',2,1.2,161,230,1,2,9.50,0.00,11.30,
     ST_SetSRID(ST_MakePoint(-73.9760,40.7555),4326),ST_SetSRID(ST_MakePoint(-73.9855,40.7580),4326)),
    (2,'2026-08-01 23:40:00+00','2026-08-01 23:52:00+00',3,2.9,230,161,1,6,0.00,0.00,0.00,
     ST_SetSRID(ST_MakePoint(-73.9855,40.7580),4326),ST_SetSRID(ST_MakePoint(-73.9760,40.7555),4326));
