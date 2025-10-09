-- Migration 1.1.0: Add warning threshold columns to timer_config

ALTER TABLE timer_config ADD COLUMN pre_draw_warning_threshold INTEGER NOT NULL DEFAULT 300;
ALTER TABLE timer_config ADD COLUMN running_warning_threshold INTEGER NOT NULL DEFAULT 900;

-- Ensure all existing rows have the correct values (for SQLite compatibility)
UPDATE timer_config SET pre_draw_warning_threshold = 300 WHERE pre_draw_warning_threshold IS NULL;
UPDATE timer_config SET running_warning_threshold = 900 WHERE running_warning_threshold IS NULL;
