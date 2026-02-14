from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .db import get_db
from .models import DashboardSession, DashboardUser

SESSION_COOKIE = "kvm_dashboard_session"
SESSION_HOURS = int(os.getenv("DASHBOARD_SESSION_HOURS", "12"))
DEFAULT_ADMIN_USER = os.getenv("DASHBOARD_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DASHBOARD_ADMIN_PASSWORD", "admin123")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def ensure_default_admin(db: Session) -> None:
    user = db.query(DashboardUser).filter(DashboardUser.username == DEFAULT_ADMIN_USER).first()
    if user:
        return
    db.add(
        DashboardUser(
            username=DEFAULT_ADMIN_USER,
            password_hash=_hash_password(DEFAULT_ADMIN_PASSWORD),
            role="admin",
            is_active=1,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def _active_session(request: Request, db: Session) -> DashboardSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.query(DashboardSession).filter(DashboardSession.token == token).first()
    if not session:
        return None
    if session.expires_at < datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        return None
    return session


def require_ui_auth(request: Request, db: Session = Depends(get_db)) -> DashboardUser:
    ensure_default_admin(db)
    session = _active_session(request, db)
    if not session:
        raise HTTPException(status_code=401, detail="login required")
    user = db.query(DashboardUser).filter(DashboardUser.id == session.user_id, DashboardUser.is_active == 1).first()
    if not user:
        raise HTTPException(status_code=401, detail="invalid session")
    return user


def render_login_page(error: str = "") -> str:
    err = f"<div style='color:#ff9cbc;margin-bottom:8px'>{error}</div>" if error else ""
    return f"""
<!doctype html>
<html>
  <head>
    <meta charset='utf-8' />
    <meta name='viewport' content='width=device-width, initial-scale=1' />
    <title>KVM Dashboard Login</title>
    <style>
      body {{ background:#1f2633; color:#ecf1fa; font-family:Inter,system-ui,sans-serif; margin:0; display:grid; place-items:center; min-height:100vh; }}
      .card {{ width:min(430px,92vw); background:#263145; border:1px solid #3a4a62; border-radius:10px; padding:18px; }}
      input {{ width:100%; box-sizing:border-box; margin:6px 0 10px; background:#0f1a3b; border:1px solid #2a447f; color:#dce7ff; border-radius:8px; padding:9px; }}
      button {{ width:100%; border:1px solid #2f5dad; background:#123777; color:#e8f2ff; padding:10px; border-radius:8px; cursor:pointer; }}
      .muted {{ color:#a9b6cc; font-size:12px; margin-top:8px; }}
    </style>
  </head>
  <body>
    <form class='card' method='post' action='/login'>
      <h2 style='margin-top:0'>KVM Dashboard Login</h2>
      {err}
      <label>Username</label>
      <input name='username' placeholder='admin' required />
      <label>Password</label>
      <input name='password' type='password' required />
      <button type='submit'>Login</button>
      <div class='muted'>Default user can be controlled with DASHBOARD_ADMIN_USER / DASHBOARD_ADMIN_PASSWORD.</div>
    </form>
  </body>
</html>
"""


def login_get(db: Session = Depends(get_db)) -> HTMLResponse:
    ensure_default_admin(db)
    return HTMLResponse(render_login_page())


def login_post(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)) -> RedirectResponse | HTMLResponse:
    ensure_default_admin(db)
    user = db.query(DashboardUser).filter(DashboardUser.username == username, DashboardUser.is_active == 1).first()
    if not user or not hmac.compare_digest(user.password_hash, _hash_password(password)):
        return HTMLResponse(render_login_page("Invalid username or password"), status_code=401)

    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    db.add(DashboardSession(user_id=user.id, token=token, created_at=datetime.now(timezone.utc), expires_at=expires))
    db.commit()

    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=False, max_age=SESSION_HOURS * 3600)
    return response


def logout_post(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.query(DashboardSession).filter(DashboardSession.token == token).delete()
        db.commit()
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
