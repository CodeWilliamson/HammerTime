-- Migration 1.3.0: Add show_admin_url flag to timer_config

ALTER TABLE timer_config ADD COLUMN show_admin_url INTEGER NOT NULL DEFAULT 1;
UPDATE timer_config SET show_admin_url = 1 WHERE show_admin_url IS NULL;