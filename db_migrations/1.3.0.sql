-- Migration 1.3.0: Add show_admin_url flag to timer_config

ALTER TABLE timer_config ADD COLUMN show_admin_url INTEGER NOT NULL DEFAULT 1;
