"""Test script to reproduce the chat error."""
import asyncio, sys, hashlib, secrets
sys.path.insert(0, 'backend')
from backend.database import AsyncSessionLocal
from sqlalchemy import text
from datetime import datetime, timezone, timedelta

async def test():
    async with AsyncSessionLocal() as s:
        # Create auth token
        r = await s.execute(text('SELECT id FROM users LIMIT 1'))
        uid = r.first()[0]
        token = secrets.token_urlsafe(32)
        th = hashlib.sha256(token.encode()).hexdigest()
        exp = datetime.now(timezone.utc) + timedelta(days=30)
        await s.execute(text('DELETE FROM auth_sessions'))
        await s.execute(text("INSERT INTO auth_sessions (id, user_id, token_hash, expires_at, created_at) VALUES (:id, :uid, :th, :exp, :now)"),
                       {'id': secrets.token_hex(6), 'uid': uid, 'th': th, 'exp': exp, 'now': datetime.now(timezone.utc)})
        await s.commit()
        print(f"TOKEN:{token}")

asyncio.run(test())
