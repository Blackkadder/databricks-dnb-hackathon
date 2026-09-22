-- Copyright 2026 Databricks, Inc.
-- SPDX-License-Identifier: Apache-2.0
--
-- Branch-demo migration V01_02: backfill a $2.50 congestion surcharge for trips
-- that were picked up in Manhattan.
UPDATE trips t SET congestion_surcharge = 2.50
  FROM taxi_zones z
 WHERE z.location_id = t.pickup_location_id AND z.borough = 'Manhattan';
