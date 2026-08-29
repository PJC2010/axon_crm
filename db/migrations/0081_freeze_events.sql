-- Freeze/winter storm events, separate from the damage-storm columns.
--
-- pipeline/storm.py already matches NOAA/IEM Local Storm Reports to properties
-- and writes last_storm_date / last_storm_type / hail_size_in. Those columns
-- describe HAIL, WIND and TORNADO — the damage a roofer, fencer or pressure
-- washer sells against. A freeze is a different demand event driving a
-- different trade: it cracks heat exchangers, bursts condensate lines and kills
-- compressors across a whole market at once, which sells HVAC and (through
-- multi-day outages) battery-attached solar.
--
-- They are separate columns rather than more values in last_storm_type because
-- one column cannot hold both without the newer event erasing the other. Houston
-- logged 120 SNOW reports in January 2025 and 122 HAIL reports across the same
-- 24 months; folding freezes into last_storm_date would have overwritten every
-- roofing lead's hail date with a snow date, silently zeroing the storm signal
-- for the vertical that depends on it most.
--
-- The freeze recency window (config.FREEZE_RECENCY_MAX_MO, 36 months) is
-- deliberately wider than the storm window: hail sells a roof this season, but a
-- hard freeze kills equipment on a delay and the replacement wave behind one
-- runs for years. Winter Storm Uri (February 2021) is the reference case.
ALTER TABLE properties ADD COLUMN IF NOT EXISTS last_freeze_date  DATE;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS freeze_count_24mo INTEGER;

-- parcels caches the tenant-INDEPENDENT half of a property, and a freeze
-- footprint is exactly that: a free, objective fact about where the parcel sits,
-- identical for every account that seeds the ZIP. It belongs beside the storm
-- columns in pipeline/parcels.py::SHARED_COLS for the same reason they do.
ALTER TABLE parcels ADD COLUMN IF NOT EXISTS last_freeze_date  DATE;
ALTER TABLE parcels ADD COLUMN IF NOT EXISTS freeze_count_24mo INTEGER;
