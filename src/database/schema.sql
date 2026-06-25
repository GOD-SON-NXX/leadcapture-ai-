-- LeadCapture AI — Database Schema
-- SQLite auto-creates on first run via connection.py

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_name TEXT NOT NULL,
    website TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    rating REAL DEFAULT 0.0,
    review_count INTEGER DEFAULT 0,
    has_chatbot INTEGER DEFAULT 0,
    score REAL DEFAULT 0.0,
    status TEXT DEFAULT 'fresh' CHECK(status IN ('fresh','audited','pilot','paid','dead')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(phone, website)
);

CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    score REAL DEFAULT 0.0,
    email_sent_at DATETIME,
    opened INTEGER DEFAULT 0,
    clicked INTEGER DEFAULT 0,
    responded INTEGER DEFAULT 0,
    email_html TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    business_name TEXT NOT NULL,
    owner_name TEXT,
    owner_email TEXT,
    email TEXT,
    website TEXT,
    services TEXT,
    hours TEXT,
    chatbot_embed_code TEXT UNIQUE,
    status TEXT DEFAULT 'trial' CHECK(status IN ('trial','active','expired','grace')),
    trial_ends_at DATETIME,
    monthly_due_date TEXT,
    payment_status TEXT DEFAULT 'unpaid' CHECK(payment_status IN ('unpaid','paid','pending','failed')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    customer_name TEXT,
    customer_phone TEXT,
    service_needed TEXT,
    zip_code TEXT,
    preferred_time TEXT,
    messages_json TEXT DEFAULT '[]',
    status TEXT DEFAULT 'active' CHECK(status IN ('active','closed','escalated')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER,
    lead_id INTEGER,
    template_name TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    opened INTEGER DEFAULT 0,
    clicked INTEGER DEFAULT 0,
    tracking_id TEXT UNIQUE,
    FOREIGN KEY (business_id) REFERENCES businesses(id),
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    wise_reference TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending','paid','failed')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    verified_at DATETIME,
    FOREIGN KEY (business_id) REFERENCES businesses(id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_city ON leads(city, state);
CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status);
CREATE INDEX IF NOT EXISTS idx_conversations_business ON conversations(business_id);
CREATE INDEX IF NOT EXISTS idx_payments_business ON payments(business_id);
CREATE INDEX IF NOT EXISTS idx_emails_tracking ON emails(tracking_id);
