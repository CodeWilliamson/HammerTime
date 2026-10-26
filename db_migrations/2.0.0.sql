-- Migration 2.0.0: Add message_color column to timer_config
ALTER TABLE timer_config ADD COLUMN message_color VARCHAR(20) NOT NULL DEFAULT '#eeeeee';
UPDATE timer_config SET message_color = '#eeeeee' WHERE message_color IS NULL;
