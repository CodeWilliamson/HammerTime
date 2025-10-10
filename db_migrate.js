/*
 * Database Migration Script for HammerTime
 *
 * This script automatically applies all SQL migration files in the db_migrations directory
 * (e.g., 1.0.0.sql, 1.1.0.sql, etc.) to the SQLite database. It ensures that the database
 * schema is up to date with the latest version required by the application.
 *
 * - Migration files must be named with semantic versioning (e.g., 1.0.0.sql).
 * - The script checks which migrations have already been applied and only runs new ones.
 * - It maintains a migration history table in the database to track applied migrations.
 *
 * Usage:
 *   node db_migrations/migrate.js
 *
 * This should be run automatically at application startup or as part of your deployment process.
 */

import fs from 'fs';
import path from 'path';
import Database from 'better-sqlite3';
import semver from 'semver';

// Ensure the data directory exists before opening the database
const dataDir = './data';
if (!fs.existsSync(dataDir)) {
  fs.mkdirSync(dataDir, { recursive: true });
}

const db = new Database('./data/schedule.db');
// Read version from package.json in ESM-compatible way
const pkg = JSON.parse(fs.readFileSync('./package.json'));
const { version: appSchemaVersion } = pkg;
console.log(`App version: ${appSchemaVersion}`);

// 1️⃣ Ensure schema_version table exists
db.prepare(`
  CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT NOT NULL
  );
`).run();

// 2️⃣ Get current schema version (default 0.0.0 if not set)
let row = db.prepare('SELECT version FROM schema_version').get();
let currentVersion = row ? row.version : '0.0.0';
console.log(`Current DB schema version: ${currentVersion}`);
console.log(`Target schema version: ${appSchemaVersion}`);

// 3️⃣ Collect and sort all migration files using semver
const migrationFiles = fs.readdirSync('db_migrations')
  .filter(f => f.endsWith('.sql'))
  .sort((a, b) => semver.compare(a.replace('.sql', ''), b.replace('.sql', '')));

// 4️⃣ Run migrations that are newer than current version and <= target
for (const file of migrationFiles) {
  const fileVersion = file.replace('.sql', '');
  if (semver.gt(fileVersion, currentVersion) && semver.lte(fileVersion, appSchemaVersion)) {
    console.log(`➡️ Running migration ${fileVersion}...`);

    const sql = fs.readFileSync(path.join('db_migrations', file), 'utf8');

    // Run inside a transaction for safety
    const transaction = db.transaction(() => {
      db.exec(sql);
    });

    try {
      transaction();
      console.log(`✅ Migration ${fileVersion} applied successfully.`);
      // Update schema_version table
      db.prepare('DELETE FROM schema_version').run();
      db.prepare('INSERT INTO schema_version (version) VALUES (?)').run(fileVersion);
      currentVersion = fileVersion;
    } catch (err) {
      console.error(`❌ Migration ${fileVersion} failed:`, err.message);
      console.log('Rolling back...');
      break; // stop further migrations
    }
  }
}

console.log(`📦 Database schema is now at version ${currentVersion}`);