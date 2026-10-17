-- Migration 1.5.0: Add dynamic_timer_format flag to timer_config
ALTER TABLE timer_config ADD COLUMN dynamic_timer_format INTEGER NOT NULL DEFAULT 0;
UPDATE timer_config SET dynamic_timer_format = 0 WHERE dynamic_timer_format IS NULL;
