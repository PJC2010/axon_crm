-- Auth: users table + FK columns on existing tables
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    username    TEXT NOT NULL UNIQUE,
    hashed_pw   TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'owner',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);

ALTER TABLE properties      ADD COLUMN IF NOT EXISTS owner_id INT REFERENCES users(id);
ALTER TABLE contact_notes   ADD COLUMN IF NOT EXISTS created_by INT REFERENCES users(id);
ALTER TABLE contact_history ADD COLUMN IF NOT EXISTS created_by INT REFERENCES users(id);
