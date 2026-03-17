-- Migration 1.2.0: Add timer_color column to timer_config

ALTER TABLE timer_config ADD COLUMN timer_color INTEGER NOT NULL DEFAULT '#eeeeee';

-- Ensure all existing rows have the correct values (for SQLite compatibility)
UPDATE timer_config SET timer_color = '#eeeeee' WHERE timer_color IS NULL;