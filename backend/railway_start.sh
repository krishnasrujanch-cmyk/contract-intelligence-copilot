#!/bin/bash
set -e

echo "=== Railway Startup ==="

# Create dirs
mkdir -p /app/backend/keys /app/uploads /app/chroma_data

# Generate JWT keys
if [ ! -f /app/backend/keys/private.pem ]; then
    openssl genrsa -out /app/backend/keys/private.pem 2048
    openssl rsa -in /app/backend/keys/private.pem -pubout -out /app/backend/keys/public.pem
    echo "JWT keys generated"
fi

# Fix DATABASE_URL
if [ ! -z "$DATABASE_URL" ]; then
    export DATABASE_URL=$(echo "$DATABASE_URL" | tr -d ' ' | \
        sed 's|^postgres://|postgresql+asyncpg://|' | \
        sed 's|^postgresql://|postgresql+asyncpg://|')
fi

cd /app/backend

# Create tables and seed using Python with asyncpg directly
/opt/venv/bin/python << 'PYEOF'
import asyncio, os, sys, uuid
sys.path.insert(0, '/app/backend')

async def setup():
    import asyncpg
    db_url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', '')
    conn = await asyncpg.connect(f'postgresql://{db_url.split("//")[-1]}')
    
    # Create tables
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS organisations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID REFERENCES organisations(id),
            email VARCHAR(255) UNIQUE NOT NULL,
            full_name VARCHAR(255),
            hashed_password VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'viewer',
            is_active BOOLEAN DEFAULT TRUE,
            last_login TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS contracts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID REFERENCES organisations(id),
            uploaded_by UUID REFERENCES users(id),
            title VARCHAR(500),
            original_filename VARCHAR(500),
            file_path TEXT,
            file_type VARCHAR(50),
            status VARCHAR(50) DEFAULT 'uploaded',
            overall_risk VARCHAR(50),
            risk_score INTEGER,
            page_count INTEGER,
            file_size INTEGER,
            contract_metadata JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS clauses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id UUID REFERENCES contracts(id),
            org_id UUID REFERENCES organisations(id),
            clause_type VARCHAR(100),
            title VARCHAR(500),
            raw_text TEXT,
            summary TEXT,
            risk_score INTEGER,
            risk_level VARCHAR(50),
            risk_reason TEXT,
            extraction_confidence FLOAT,
            flagged_for_review BOOLEAN DEFAULT FALSE,
            extracted_data JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS user_contract_assignments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            contract_id UUID REFERENCES contracts(id),
            assigned_by UUID REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            clause_id UUID,
            contract_id UUID,
            user_id UUID,
            is_positive BOOLEAN,
            feedback_target VARCHAR(100),
            suggested_value VARCHAR(255),
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID,
            user_id UUID,
            user_role VARCHAR(50),
            action VARCHAR(100),
            resource_type VARCHAR(100),
            resource_id UUID,
            log_context JSONB DEFAULT '{}',
            timestamp TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            token_hash VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    print("Tables created")
    
    # Seed demo data
    from passlib.context import CryptContext
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    org_id = str(uuid.uuid4())
    try:
        await conn.execute(
            "INSERT INTO organisations (id, name) VALUES ($1, $2)",
            org_id, "Demo Organisation"
        )
    except Exception:
        row = await conn.fetchrow("SELECT id FROM organisations LIMIT 1")
        org_id = str(row['id'])
    
    users = [
        ("admin@clm.demo", "Admin User", "Admin@Demo2026!", "admin"),
        ("reviewer@clm.demo", "Reviewer User", "Review@Demo2026!", "reviewer"),
        ("viewer@clm.demo", "Viewer User", "View@Demo2026!", "viewer"),
    ]
    for email, name, password, role in users:
        try:
            await conn.execute("""
                INSERT INTO users (id, org_id, email, full_name, hashed_password, role)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (email) DO NOTHING
            """, str(uuid.uuid4()), org_id, email, name, pwd.hash(password), role)
            print(f"User: {email}")
        except Exception as e:
            print(f"Skip {email}: {e}")
    
    await conn.close()
    print("Setup complete")

asyncio.run(setup())
PYEOF

# Start server
echo "Starting server on port ${PORT:-8000}..."
/opt/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
