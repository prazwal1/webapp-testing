CREATE TABLE IF NOT EXISTS notes (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT,
    attachment_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
