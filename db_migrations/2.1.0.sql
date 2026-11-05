-- Migration 2.1.0: end-of-game counter
--
-- Each draw can carry a "time per end"; the kiosk turns it into an END n badge while the
-- draw is running. NULL means the counter is off for that draw, so existing rows are
-- untouched and the feature only appears once an admin opts in per draw.
ALTER TABLE draws ADD COLUMN end_minutes INTEGER;
ALTER TABLE draw_overrides ADD COLUMN end_minutes INTEGER;

-- Global on/off for the display (Display Settings -> End counter).
ALTER TABLE timer_config ADD COLUMN show_end_number INTEGER NOT NULL DEFAULT 0;
UPDATE timer_config SET show_end_number = 0 WHERE show_end_number IS NULL;

-- Enlarged end number at the start of an end
--
-- The END n badge can start each end enlarged to draw attention and shrink back to the
-- normal label size partway through. All of that is a display preference rather than
-- draw data, so it lives on the single timer_config row:
--
--   end_highlight_percent        how much of each end stays enlarged (50 = first half,
--                                0 = never enlarge)
--   end_highlight_scale          how much bigger the badge gets (relative to the status
--                                label size)
--   end_highlight_timer_percent  the countdown's size while the badge is enlarged, so it
--                                shrinks to make room instead of pushing content off the
--                                screen
ALTER TABLE timer_config ADD COLUMN end_highlight_percent INTEGER NOT NULL DEFAULT 50;
ALTER TABLE timer_config ADD COLUMN end_highlight_scale REAL NOT NULL DEFAULT 1.5;
ALTER TABLE timer_config ADD COLUMN end_highlight_timer_percent INTEGER NOT NULL DEFAULT 75;
