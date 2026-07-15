import asyncio, os, sys, uuid
sys.path.insert(0, '/app/backend')

async def setup():
    import asyncpg, bcrypt
    db_url = os.environ.get('DATABASE_URL','').replace('postgresql+asyncpg://', 'postgresql://')
    if 'neon.tech' in db_url and 'ssl' not in db_url:
        db_url += '?ssl=require'
    conn = await asyncpg.connect(db_url)
    print('Connected!')

    # Drop all tables
    tables = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    for t in tables:
        await conn.execute(f'DROP TABLE IF EXISTS {t[0]} CASCADE')
    print('Dropped tables')

    # Create from SQLAlchemy models
    from app.domain.models import Base
    from sqlalchemy.schema import CreateTable
    from sqlalchemy.dialects.postgresql import dialect as pg_dialect
    d = pg_dialect()
    for table in Base.metadata.sorted_tables:
        try:
            ddl = str(CreateTable(table).compile(dialect=d))
            await conn.execute(ddl)
            print(f'Created: {table.name}')
        except Exception as e:
            print(f'Skip {table.name}: {e}')

    # Get or create org
    org_row = await conn.fetchrow("SELECT id FROM organizations LIMIT 1")
    if not org_row:
        org_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO organizations (id, name, slug, plan, risk_thresholds, llm_provider, settings, is_active, created_at, updated_at) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7::jsonb,TRUE,NOW(),NOW())",
            org_id, 'Demo Organisation', 'demo', 'free',
            '{"low":30,"medium":60,"high":80}', 'groq', '{}'
        )
        print(f'Created org: {org_id}')
    else:
        org_id = str(org_row['id'])

    # Seed users with ON CONFLICT to prevent duplicates
    for email, name, password, role in [
        ('admin@clm.demo', 'Admin User', 'Admin@Demo2026!', 'admin'),
        ('reviewer@clm.demo', 'Reviewer User', 'Review@Demo2026!', 'reviewer'),
        ('viewer@clm.demo', 'Viewer User', 'View@Demo2026!', 'viewer'),
    ]:
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
        await conn.execute(
            'INSERT INTO users (id, org_id, email, password_hash, full_name, role, is_active, login_attempts) VALUES ($1,$2,$3,$4,$5,$6,TRUE,0) ON CONFLICT (email) DO NOTHING',
            str(uuid.uuid4()), org_id, email, hashed, name, role
        )
        print(f'User ready: {email}')

    await conn.close()
    print('DB setup complete!')

asyncio.run(setup())
