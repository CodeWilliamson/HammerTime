CREATE TABLE
    IF NOT EXISTS draws (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day_of_week TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT,
        start_time TEXT NOT NULL, -- e.g., "19:00"
        duration_minutes INTEGER NOT NULL
    );

CREATE TABLE
    IF NOT EXISTS draw_overrides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL, -- ISO format "YYYY-MM-DD"
        title TEXT NOT NULL,
        message TEXT,
        start_time TEXT NOT NULL, -- "HH:mm"
        duration_minutes INTEGER NOT NULL
    );

CREATE TABLE
    IF NOT EXISTS timer_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        background_color VARCHAR(20) NOT NULL DEFAULT '#000000',
        background_color_running VARCHAR(20) NOT NULL DEFAULT '#1adb00',
        background_color_warning VARCHAR(20) NOT NULL DEFAULT '#ffae00',
        background_color_critical VARCHAR(20) NOT NULL DEFAULT '#ff0000',
        timer_color_running VARCHAR(20) NOT NULL DEFAULT '#000000',
        timer_color_warning VARCHAR(20) NOT NULL DEFAULT '#000000',
        timer_color_critical VARCHAR(20) NOT NULL DEFAULT '#000000',
        status_color VARCHAR(20) NOT NULL DEFAULT '#eeeeee',
        status_color_running VARCHAR(20) NOT NULL DEFAULT '#000000',
        status_color_warning VARCHAR(20) NOT NULL DEFAULT '#000000',
        status_color_critical VARCHAR(20) NOT NULL DEFAULT '#000000',
        message_color_running VARCHAR(20) NOT NULL DEFAULT '#000000',
        message_color_warning VARCHAR(20) NOT NULL DEFAULT '#000000',
        message_color_critical VARCHAR(20) NOT NULL DEFAULT '#000000',
        timer_font_size VARCHAR(10) NOT NULL DEFAULT '28vw',
        label_font_size VARCHAR(10) NOT NULL DEFAULT '5vw',
        message_font_size VARCHAR(10) NOT NULL DEFAULT '5vw',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

INSERT INTO
    timer_config (
        background_color,
        background_color_running,
        background_color_warning,
        background_color_critical,
        timer_color_running,
        timer_color_warning,
        timer_color_critical,
        status_color,
        status_color_running,
        status_color_warning,
        status_color_critical,
        message_color_running,
        message_color_warning,
        message_color_critical,
        timer_font_size,
        label_font_size,
        message_font_size
    )
SELECT
    '#000000',
    '#1adb00',
    '#ffae00',
    '#ff0000',
    '#000000',
    '#000000',
    '#000000',
    '#eeeeee',
    '#000000',
    '#000000',
    '#000000',
    '#000000',
    '#000000',
    '#000000',
    '28vw',
    '5vw',
    '5vw'
WHERE
    NOT EXISTS (
        SELECT
            1
        FROM
            timer_config
    );

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
  );

-- Insert default timer user if does not exists (password: 'timer', bcrypt hash)
INSERT INTO users (username, password_hash)
SELECT 'timer', '$2b$10$XxAl8yrxI6aaLlbEvsL4COx9tPE6K7vM6nUL3t9v5Vi2cAzwPF9ty'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'timer');