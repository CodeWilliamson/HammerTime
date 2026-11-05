-- Migration 2.1.0: end-of-game counter
--
-- Each draw can carry a "time per end"; the kiosk turns it into an END n badge while the
-- draw is running. NULL means the counter is off for that draw, so existing rows are
-- untouched and the feature only appears once an admin opts in per draw.
ALTER TABLE draws ADD COLUMN end_minutes INTEGER;
ALTER TABLE draw_overrides ADD COLUMN end_minutes INTEGER;

-- Global on/off for the display (Display Settings -> Display Behavior).
ALTER TABLE timer_config ADD COLUMN show_end_number INTEGER NOT NULL DEFAULT 0;
UPDATE timer_config SET show_end_number = 0 WHERE show_end_number IS NULL;
