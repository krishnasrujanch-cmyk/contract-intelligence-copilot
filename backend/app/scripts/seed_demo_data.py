"""Demo data seeder — creates org + 3 demo users on first run."""
from __future__ import annotations
import asyncio, uuid
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.domain.models import Base, Organization, User
from app.infrastructure.database.session import AsyncSessionLocal, engine

configure_logging()
logger = get_logger(__name__)

async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        existing = await db.execute(select(Organization).where(Organization.slug == "clm-demo"))
        if existing.scalar_one_or_none():
            logger.info("demo_data_already_seeded"); return
        org = Organization(id=uuid.uuid4(), name="CLM Demo Org", slug="clm-demo", plan="starter")
        db.add(org); await db.flush()
        for email, pwd, name, role in [
            (settings.demo_admin_email,    settings.demo_admin_password,    "Admin User",    "admin"),
            (settings.demo_reviewer_email, settings.demo_reviewer_password, "Reviewer User", "reviewer"),
            (settings.demo_viewer_email,   settings.demo_viewer_password,   "Viewer User",   "viewer"),
        ]:
            db.add(User(org_id=org.id, email=email, password_hash=hash_password(pwd),
                        full_name=name, role=role, is_active=True))
        await db.commit()
        print(f"\n✅ Seeded: admin@clm.demo / reviewer@clm.demo / viewer@clm.demo")

if __name__ == "__main__":
    asyncio.run(seed())
