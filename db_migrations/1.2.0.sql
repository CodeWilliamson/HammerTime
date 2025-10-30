-- Migration 1.1.0: Add warning threshold columns to timer_config

ALTER TABLE timer_config ADD COLUMN timer_color INTEGER NOT NULL DEFAULT '#ffffffff';

-- Ensure all existing rows have the correct values (for SQLite compatibility)
UPDATE timer_config SET timer_color = '#ffffffff' WHERE timer_color IS NULL;