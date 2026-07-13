#!/bin/bash
set -e
echo "=== Railway Startup ==="

mkdir -p /app/backend/keys /app/uploads /app/chroma_data

# Generate JWT keys
if [ ! -f /app/backend/keys/private.pem ]; then
    openssl genrsa -out /app/backend/keys/private.pem 2048
    openssl rsa -in /app/backend/keys/private.pem -pubout -out /app/backend/keys/public.pem
    echo "JWT keys generated"
fi

# Fix DATABASE_URL format
if [ ! -z "$DATABASE_URL" ]; then
    export DATABASE_URL=$(echo "$DATABASE_URL" | tr -d ' ' | \
        sed 's|^postgres://|postgresql+asyncpg://|' | \
        sed 's|^postgresql://|postgresql+asyncpg://|')
fi

cd /app/backend

# Setup DB and seed
/opt/venv/bin/python << 'PYEOF'
import asyncio, os, sys, uuid
sys.path.insert(0, '/app/backend')

async def setup():
    import asyncpg
    db_url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(db_url)
    
    # Create tables from SQLAlchemy models
    from app.domain.models import Base
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects import postgresql
    
    for table in Base.metadata.sorted_tables:
        try:
            ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
            await conn.execute(f"DROP TABLE IF EXISTS {table.name} CASCADE")
            await conn.execute(ddl)
        except Exception as e:
            print(f"Table {table.name}: {e}")
    
    # Seed org and users
    org = await conn.fetchrow("SELECT id FROM organizations LIMIT 1")
    if org:
        org_id = str(org['id'])
    else:
        org_id = str(uuid.uuid4())
        await conn.execute("""
            INSERT INTO organizations 
            (id, name, slug, plan, risk_thresholds, llm_provider, settings, is_active, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7::jsonb,TRUE,NOW(),NOW())
        """, org_id, "Demo Organisation", "demo", "free",
            '{"low":30,"medium":60,"high":80}', "groq", '{}')
    
    from app.core.security import hash_password
    for email, name, password, role in [
        ("admin@clm.demo", "Admin User", "Admin@Demo2026!", "admin"),
        ("reviewer@clm.demo", "Reviewer User", "Review@Demo2026!", "reviewer"),
        ("viewer@clm.demo", "Viewer User", "View@Demo2026!", "viewer"),
    ]:
        hashed = hash_password(password)
        await conn.execute("DELETE FROM users WHERE email=$1", email)
        await conn.execute("""
            INSERT INTO users (id,org_id,email,password_hash,full_name,role,is_active,login_attempts)
            VALUES ($1,$2,$3,$4,$5,$6,TRUE,0)
        """, str(uuid.uuid4()), org_id, email, hashed, name, role)
        print(f"✓ {email}")
    
    await conn.close()
    print("Setup complete")

asyncio.run(setup())
PYEOF

echo "Starting server..."
/opt/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
