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
    for t in ['refresh_tokens','audit_log','audit_logs','feedback',
              'user_contract_assignments','clauses','contracts','users',
              'organisations','organizations','alerts','obligations']:
        await conn.execute(f'DROP TABLE IF EXISTS {t} CASCADE')
    print('Dropped old tables')

    # Create with organizations (US - matches SQLAlchemy model FK)
    await conn.execute('''
        CREATE TABLE organizations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(255) NOT NULL,
            settings JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID REFERENCES organizations(id),
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            full_name VARCHAR(255),
            role VARCHAR(50) DEFAULT 'viewer',
            is_active BOOLEAN DEFAULT TRUE,
            login_attempts INTEGER DEFAULT 0,
            locked_until TIMESTAMP,
            last_login TIMESTAMP,
            created_by UUID,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE contracts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID REFERENCES organizations(id),
            uploaded_by UUID REFERENCES users(id),
            title VARCHAR(500),
            original_filename VARCHAR(500),
            file_path TEXT,
            file_type VARCHAR(50),
            file_size INTEGER,
            status VARCHAR(50) DEFAULT 'uploaded',
            overall_risk VARCHAR(50),
            risk_score INTEGER,
            page_count INTEGER,
            contract_metadata JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE clauses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id UUID REFERENCES contracts(id),
            org_id UUID REFERENCES organizations(id),
            clause_type VARCHAR(100),
            title VARCHAR(500),
            raw_text TEXT,
            summary TEXT,
            risk_score INTEGER,
            risk_level VARCHAR(50),
            risk_reason TEXT,
            suggested_revision TEXT,
            extraction_confidence FLOAT,
            flagged_for_review BOOLEAN DEFAULT FALSE,
            judge_verdict VARCHAR(50),
            extracted_data JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE user_contract_assignments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            contract_id UUID REFERENCES contracts(id),
            assigned_by UUID REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE feedback (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            clause_id UUID, contract_id UUID, user_id UUID,
            is_positive BOOLEAN, feedback_target VARCHAR(100),
            suggested_value VARCHAR(255), original_value VARCHAR(255),
            notes TEXT, created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID, user_id UUID, user_role VARCHAR(50),
            action VARCHAR(100), resource_type VARCHAR(100),
            resource_id UUID, ip_hash VARCHAR(255),
            trace_id VARCHAR(255), duration_ms INTEGER,
            context JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    await conn.execute('''
        CREATE TABLE refresh_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            token_hash VARCHAR(255) UNIQUE NOT NULL,
            jti VARCHAR(255),
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            revoked BOOLEAN DEFAULT FALSE,
            revoked_at TIMESTAMP WITH TIME ZONE,
            ip_hash VARCHAR(255), device_hint VARCHAR(255),
            issued_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    ''')
    print('Tables created')

    # Seed users
    org_id = str(uuid.uuid4())
    await conn.execute(
        'INSERT INTO organizations (id, name) VALUES ($1, $2)',
        org_id, 'Demo Organisation'
    )
    for email, name, password, role in [
        ('admin@clm.demo', 'Admin User', 'Admin@Demo2026!', 'admin'),
        ('reviewer@clm.demo', 'Reviewer User', 'Review@Demo2026!', 'reviewer'),
        ('viewer@clm.demo', 'Viewer User', 'View@Demo2026!', 'viewer'),
    ]:
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
        await conn.execute(
            'INSERT INTO users (id, org_id, email, password_hash, full_name, role, is_active, login_attempts) VALUES ($1, $2, $3, $4, $5, $6, TRUE, 0)',
            str(uuid.uuid4()), org_id, email, hashed, name, role
        )
        print(f'Created: {email}')

    await conn.close()
    print('DB setup complete!')

asyncio.run(setup())
