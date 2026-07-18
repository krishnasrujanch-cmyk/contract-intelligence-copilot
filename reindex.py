import asyncio, os, sys, time
sys.path.insert(0, '/app/backend')

# Wait for server to start
time.sleep(10)

async def reindex():
    import asyncpg
    db_url = os.environ.get('DATABASE_URL','').replace('postgresql+asyncpg://', 'postgresql://')
    if 'neon.tech' in db_url and 'ssl' not in db_url:
        db_url += '?ssl=require'
    
    try:
        conn = await asyncpg.connect(db_url)
        contracts = await conn.fetch(
            "SELECT id::text, org_id::text, title, file_path, original_filename FROM contracts WHERE status='analyzed'"
        )
        print(f'Re-indexing {len(contracts)} contracts into ChromaDB...')
        await conn.close()
    except Exception as e:
        print(f'DB error: {e}')
        return

    from app.agents.rag.pipeline import RAGPipeline
    from app.infrastructure.parsers import ParserFactory
    from pathlib import Path

    pipeline = RAGPipeline()

    for row in contracts:
        try:
            cid = row['id']
            oid = row['org_id']
            fpath = row['file_path']
            fname = row['original_filename']

            if not fpath or not Path(fpath).exists():
                print(f'File missing: {fname}')
                continue

            raw = Path(fpath).read_bytes()
            parser = ParserFactory.get_parser(raw)
            parsed = parser.parse(raw, fname)
            pipeline.index_contract(parsed.text, cid, oid)
            print(f'Re-indexed: {fname}')
        except Exception as e:
            print(f'Failed {row["title"]}: {e}')

    print('Re-indexing complete')

asyncio.run(reindex())
