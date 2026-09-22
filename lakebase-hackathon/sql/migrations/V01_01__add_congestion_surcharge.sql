-- Copyright 2026 Databricks, Inc.
-- SPDX-License-Identifier: Apache-2.0
--
-- Branch-demo migration V01_01: add the congestion_surcharge column to trips.
ALTER TABLE trips ADD COLUMN IF NOT EXISTS congestion_surcharge NUMERIC(8,2) DEFAULT 0;
