-- custom_stages
CREATE TABLE IF NOT EXISTS pipeline_stages (
    id          SERIAL PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,
    label       TEXT NOT NULL,
    color       TEXT NOT NULL DEFAULT 'var(--color-ink-300)',
    sort_order  INT NOT NULL DEFAULT 0,
    is_terminal BOOLEAN NOT NULL DEFAULT FALSE,
    is_default  BOOLEAN NOT NULL DEFAULT FALSE,
    created_by  INT REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT NOW()
);

INSERT INTO pipeline_stages (key, label, color, sort_order, is_terminal, is_default) VALUES
    ('new',            'New',              'var(--color-ink-300)',  0, FALSE, TRUE),
    ('contacted',      'Contacted',        'var(--color-ocean)',   1, FALSE, FALSE),
    ('qualified',      'Qualified',        'var(--color-accent)',  2, FALSE, FALSE),
    ('quote_sent',     'Quote Sent',       'var(--color-gold)',    3, FALSE, FALSE),
    ('won',            'Won',              'var(--color-moss)',    4, TRUE,  FALSE),
    ('lost',           'Lost',             'var(--color-danger)',  5, TRUE,  FALSE),
    ('not_interested', 'Not Interested',   'var(--color-ink-200)', 6, TRUE,  FALSE)
ON CONFLICT (key) DO NOTHING;
