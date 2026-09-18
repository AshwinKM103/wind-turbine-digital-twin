-- Copilot conversation history schema
-- Stores all chat turns (user messages and assistant responses) for audit and context retrieval

CREATE TABLE IF NOT EXISTS copilot_conversations (
    id SERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast conversation retrieval by ID
CREATE INDEX IF NOT EXISTS idx_copilot_conversations_conversation_id
    ON copilot_conversations(conversation_id);

-- Index for timeline queries
CREATE INDEX IF NOT EXISTS idx_copilot_conversations_created_at
    ON copilot_conversations(created_at);
