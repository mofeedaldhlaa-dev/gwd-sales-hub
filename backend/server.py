from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import uuid
import bcrypt
import jwt
import secrets
import string
import logging
import mimetypes
import requests
from io import BytesIO
try:
    from pywebpush import webpush as _webpush
except Exception:
    _webpush = None
import gzip
import json
import hmac
import hashlib
import re as _re
import unicodedata as _unicodedata
import ipaddress
import asyncio
import httpx
from functools import wraps
from html import escape as _html_escape
from html.parser import HTMLParser
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any, Dict, Literal, Tuple
from zoneinfo import ZoneInfo
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, status, UploadFile, File, Form, Query, Header, BackgroundTasks
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image, ImageOps
import qrcode
try:
    from statement_import import parse_statement_pdf
except ImportError:
    from backend.statement_import import parse_statement_pdf
try:
    from card_pdf_import import parse_card_pdf
except ImportError:
    from backend.card_pdf_import import parse_card_pdf

# ================= CONFIG =================
MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']
JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALG = "HS256"
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
COMPANY_NAME = os.environ.get('COMPANY_NAME', 'شبكة جواد نت اللاسلكية')
COMPANY_PHONE = os.environ.get('COMPANY_PHONE', '784225716')

# ============ Object storage (Emergent integration) ============
# ============ Object storage (self-hosted: local disk) ============
# في النشر الذاتي على VPS تُخزَّن الملفات على قرص الخادم.
# يبقى مسار Emergent متاحاً كاحتياط إذا لم يُضبط LOCAL_STORAGE_DIR.
STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "jawad-net"
# ============ Email (Emergent managed Resend) ============
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", COMPANY_NAME)
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO") or None
PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
WEBHOOK_CRON_SECRET = os.environ.get("WEBHOOK_CRON_SECRET", "")
LOCAL_STORAGE_DIR = (os.environ.get("LOCAL_STORAGE_DIR") or "/app/storage").strip()
_storage_key: Optional[str] = None


def _local_storage_path(path: str) -> str:
    safe = path.strip("/").replace("..", "_")
    return os.path.join(LOCAL_STORAGE_DIR, safe)


def init_storage(force: bool = False) -> Optional[str]:
    """In self-hosted mode the local disk is always available."""
    global _storage_key
    if LOCAL_STORAGE_DIR:
        return "local-disk"
    if _storage_key and not force:
        return _storage_key
    if not EMERGENT_KEY:
        return None
    try:
        resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
        resp.raise_for_status()
        _storage_key = resp.json().get("storage_key")
        return _storage_key
    except Exception as e:
        logging.getLogger("jawad").error(f"Storage init failed: {e}")
        return None


def _put_object(path: str, data: bytes, content_type: str) -> dict:
    if LOCAL_STORAGE_DIR:
        dest = _local_storage_path(path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        try:
            with open(dest + ".meta", "w", encoding="utf-8") as fh:
                fh.write(content_type or "")
        except Exception:
            pass
        return {"path": path, "size": len(data), "content_type": content_type}
    key = init_storage()
    if not key:
        raise HTTPException(status_code=503, detail="خدمة التخزين غير متوفرة")
    resp = requests.put(f"{STORAGE_URL}/objects/{path}",
                        headers={"X-Storage-Key": key, "Content-Type": content_type},
                        data=data, timeout=120)
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.put(f"{STORAGE_URL}/objects/{path}",
                            headers={"X-Storage-Key": key, "Content-Type": content_type},
                            data=data, timeout=120)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=f"فشل الرفع: {resp.text[:120]}")
    return resp.json()


def _get_object(path: str) -> tuple:
    if LOCAL_STORAGE_DIR:
        src = _local_storage_path(path)
        if not os.path.exists(src):
            raise HTTPException(status_code=404, detail="الملف غير موجود")
        with open(src, "rb") as fh:
            data = fh.read()
        ctype = ""
        try:
            with open(src + ".meta", encoding="utf-8") as fh:
                ctype = fh.read().strip()
        except Exception:
            ctype = ""
        if not ctype:
            ctype = mimetypes.guess_type(src)[0] or "application/octet-stream"
        return data, ctype
    key = init_storage()
    if not key:
        raise HTTPException(status_code=503, detail="خدمة التخزين غير متوفرة")
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if resp.status_code == 404:
        key2 = init_storage(force=True)
        if key2 and key2 != key:
            resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key2}, timeout=60)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail="الملف غير موجود")
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


# ============ Email guardrail gate (structural G2 + G3 defense-in-depth) ============
_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = _re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", _re.I)

def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)

def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)

class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []
    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []
    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []

def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan(); scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} != real link host {real!r} (G3)")

async def send_email(*, to: str, subject: str, html: str, reply_to: Optional[str] = None) -> Optional[str]:
    if not EMAIL_KEY:
        raise HTTPException(status_code=503, detail="خدمة البريد غير مهيأة")
    _assert_safe_email(subject, html)
    payload: Dict[str, Any] = {"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    rt = reply_to or EMAIL_REPLY_TO
    if rt:
        payload["contact_email"] = rt
    try:
        async with httpx.AsyncClient(timeout=30) as client_h:
            resp = await client_h.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": EMAIL_KEY},
                json=payload,
            )
        resp.raise_for_status()
        return resp.json().get("id")
    except httpx.HTTPStatusError as e:
        logging.getLogger("jawad").error(f"Email send failed: {e.response.status_code} {e.response.text[:300]}")
        raise HTTPException(status_code=502, detail="فشل إرسال البريد")
    except Exception as e:
        logging.getLogger("jawad").error(f"Email send error: {e}")
        raise HTTPException(status_code=500, detail="فشل إرسال البريد")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
financial_mutation_lock = asyncio.Lock()
instruction_image_variant_lock = asyncio.Lock()
app = FastAPI(title="Jawad Net ERP")
BACKUP_TIMEZONE = ZoneInfo("Asia/Aden")
BACKUP_SCHEDULER_POLL_SECONDS = 30
BACKUP_SCHEDULER_STALE_SECONDS = 2 * 60 * 60
_backup_scheduler_task: Optional[asyncio.Task] = None

@app.middleware("http")
async def mutation_idempotency_middleware(request: Request, call_next):
    """Replay a completed JSON mutation instead of applying it twice.

    The frontend sends the same Idempotency-Key while retrying an offline
    operation. Core financial routes also have their domain-level guard; this
    middleware covers the remaining authenticated JSON mutations without
    touching uploads, public portal calls, reads, or destructive reset/restore
    endpoints.
    """
    method = request.method.upper()
    path = request.url.path
    excluded = ("/public/", "/auth/", "/push/", "/files/upload", "/backup/", "/settings/reset-data", "/cron/")
    if method in {"GET", "HEAD", "OPTIONS"} or not path.startswith("/api/") or any(x in path for x in excluded):
        return await call_next(request)
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" not in content_type or int(request.headers.get("content-length") or 0) > 2_000_000:
        return await call_next(request)
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        return await call_next(request)
    auth_fingerprint = hashlib.sha256((request.headers.get("authorization") or "").encode()).hexdigest()[:24]
    claim_id = f"http:{auth_fingerprint}:{method}:{path}:{key}"
    claim = await db.operation_claims.find_one({"_id": claim_id})
    if claim and claim.get("status") == "done" and claim.get("body_text") is not None:
        headers = {"content-type": claim.get("content_type") or "application/json", "x-idempotent-replay": "1"}
        return Response(content=claim["body_text"], status_code=int(claim.get("status_code") or 200), headers=headers)
    if claim and claim.get("status") == "processing":
        return Response(content=json.dumps({"detail": "العملية قيد التنفيذ ولم يتم تكرارها."}, ensure_ascii=False), status_code=409, media_type="application/json")
    try:
            await db.operation_claims.insert_one({"_id": claim_id, "scope": "http", "idempotency_key": key, "status": "processing", "created_at": now_iso()})
    except DuplicateKeyError:
        return Response(content=json.dumps({"detail": "العملية مسجلة مسبقاً أو قيد التنفيذ."}, ensure_ascii=False), status_code=409, media_type="application/json")

    response = None
    try:
        response = await call_next(request)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        if 200 <= response.status_code < 300:
            text = body.decode("utf-8", errors="replace")
            await db.operation_claims.update_one({"_id": claim_id}, {"$set": {"status": "done", "status_code": response.status_code, "body_text": text, "content_type": response.media_type or "application/json", "completed_at": now_iso()}})
        else:
            await db.operation_claims.delete_one({"_id": claim_id, "status": "processing"})
        headers = {k: v for k, v in response.headers.items() if k.lower() not in {"content-length", "transfer-encoding", "content-encoding"}}
        return Response(content=body, status_code=response.status_code, headers=headers, media_type=response.media_type)
    except Exception:
        await db.operation_claims.update_one({"_id": claim_id}, {"$set": {"status": "needs_review", "failed_at": now_iso()}})
        raise
api = APIRouter(prefix="/api")
APP_TIMEZONE = timezone(timedelta(hours=3), name="Asia/Aden")

def _server_now():
    return datetime.now(timezone.utc).astimezone(APP_TIMEZONE)

@api.get("/system/date")
async def system_date():
    now = _server_now()
    return {"iso": now.isoformat(), "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"), "timezone": "Asia/Aden", "utc_offset": "+03:00", "source": "server"}

security = HTTPBearer(auto_error=False)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jawad")


# ================= HELPERS =================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ================= ALTERNATIVE ACCOUNT NUMBERS =================
# A six-digit public identifier. It is deliberately kept outside the customer
# document as a reservation ledger so a closed/deleted account never releases
# its number for reuse.
ALTERNATIVE_NUMBER_COLLECTION = "alternative_number_reservations"
_ALTERNATIVE_NUMBER_RE = _re.compile(r"^[1-9][0-9]{5}$")

def _valid_alternative_number(value: Any) -> bool:
    return bool(_ALTERNATIVE_NUMBER_RE.fullmatch(str(value or "").strip()))

def _short_customer_name(value: Any) -> str:
    parts = [p for p in str(value or "").strip().split() if p]
    return " ".join(parts[:2])[:80] or "الحساب"

def _phone_last_two(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-2:] if len(digits) >= 2 else digits

async def _ensure_customer_alternative_number(customer: dict) -> str:
    """Return and persist one immutable number for a customer.

    The unique reservation collection is the source of truth for non-reuse.
    The customer field is a denormalized read/display copy.
    """
    customer_id = str((customer or {}).get("id") or "").strip()
    if not customer_id:
        raise ValueError("customer id is required for alternative number")
    registry = db[ALTERNATIVE_NUMBER_COLLECTION]
    current = str((customer or {}).get("alternative_number") or "").strip()
    if _valid_alternative_number(current):
        try:
            await registry.update_one(
                {"number": current},
                {"$setOnInsert": {
                    "number": current, "customer_id": customer_id,
                    "status": "reserved", "created_at": now_iso(),
                }},
                upsert=True,
            )
        except DuplicateKeyError:
            # A legacy collision is not repaired by changing an immutable value.
            # Keep the existing customer value and leave an audit trail in logs.
            logger.error("Alternative number collision for customer %s: %s", customer_id, current)
        return current

    prior = await registry.find_one({"customer_id": customer_id}, {"number": 1})
    if prior and _valid_alternative_number(prior.get("number")):
        number = str(prior["number"])
        await db.customers.update_one(
            {"id": customer_id, "alternative_number": {"$exists": False}},
            {"$set": {"alternative_number": number, "alternative_number_created_at": prior.get("created_at") or now_iso()}},
        )
        return number

    for _ in range(200):
        number = str(secrets.randbelow(900000) + 100000)
        reservation = {
            "number": number, "customer_id": customer_id, "status": "reserved",
            "created_at": now_iso(),
        }
        try:
            await registry.insert_one(reservation)
        except DuplicateKeyError:
            # A concurrent worker may have reserved this customer already.
            # Re-read by customer_id before trying a fresh random number.
            concurrent = await registry.find_one({"customer_id": customer_id}, {"number": 1})
            if concurrent and _valid_alternative_number(concurrent.get("number")):
                number = str(concurrent["number"])
                await db.customers.update_one(
                    {"id": customer_id, "alternative_number": {"$exists": False}},
                    {"$set": {"alternative_number": number, "alternative_number_created_at": concurrent.get("created_at") or now_iso()}},
                )
                return number
            continue
        result = await db.customers.update_one(
            {"id": customer_id, "alternative_number": {"$exists": False}},
            {"$set": {"alternative_number": number, "alternative_number_created_at": reservation["created_at"]}},
        )
        if result.modified_count == 1:
            return number
        # Another worker won the customer update. Keep its immutable number and
        # remove only this worker's unused reservation.
        latest = await db.customers.find_one({"id": customer_id}, {"alternative_number": 1})
        latest_number = str((latest or {}).get("alternative_number") or "").strip()
        if _valid_alternative_number(latest_number):
            await registry.delete_one({"number": number, "customer_id": customer_id})
            return latest_number
        return number
    raise RuntimeError("unable to reserve a unique alternative number")

async def _ensure_all_alternative_numbers() -> int:
    registry = db[ALTERNATIVE_NUMBER_COLLECTION]
    await registry.create_index("number", unique=True, name="alternative_number_unique")
    await registry.create_index("customer_id", unique=True, name="alternative_customer_unique")
    assigned = 0
    async for customer in db.customers.find({}, {"id": 1, "alternative_number": 1, "phone": 1, "name": 1}):
        number = await _ensure_customer_alternative_number(customer)
        if number:
            assigned += 1
    return assigned

def _recipient_phone_variants(value: Any) -> list[str]:
    raw = str(value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    local = digits.lstrip("0")
    if local.startswith("967") and len(local) > 9:
        local = local[3:]
    result: list[str] = []
    for item in (raw, digits, local, "967" + local, "0" + local, digits[-9:]):
        if item and item not in result:
            result.append(item)
    return result

async def _find_customer_by_phone_or_alternative(value: Any) -> Optional[dict]:
    raw = str(value or "").strip()
    if _valid_alternative_number(raw):
        by_alt = await db.customers.find_one({"alternative_number": raw})
        if by_alt:
            return by_alt
    variants = _recipient_phone_variants(raw)
    return await db.customers.find_one({"phone": {"$in": variants}}) if variants else None

def _public_transfer_view(doc: dict) -> dict:
    """Remove the recipient's real phone from any public transfer response."""
    item = clean_doc(doc or {})
    phone = item.get("recipient_phone") or item.get("dest_phone") or ""
    recipient = {
        "recipient_phone_last2": _phone_last_two(phone),
        "recipient_alternative_number": item.get("recipient_alternative_number") or item.get("dest_alternative_number") or "",
        "recipient_short_name": item.get("recipient_short_name") or _short_customer_name(item.get("recipient_name") or item.get("dest_name")),
    }
    # Keep the field for backward-compatible JSON shape, but never return the
    # full private phone to the public portal.
    item["recipient_phone"] = ("••••" + recipient["recipient_phone_last2"]) if recipient["recipient_phone_last2"] else ""
    item.update(recipient)
    return item


DUPLICATE_OPERATION_WINDOW_SECONDS = 120

def _is_native_pos_customer(customer: Dict[str, Any]) -> bool:
    """Return True only for a native POS account, not a custom subtype."""
    return (
        str(customer.get("customer_type") or "").strip().lower() == "pos"
        and not str(customer.get("account_type") or "").strip()
    )

BASE_ACCOUNT_TYPES = ("customer", "pos", "supplier", "expense", "unverified")

async def _resolve_custom_account_type(raw_type: Optional[str], allowed: tuple[str, ...] = BASE_ACCOUNT_TYPES) -> Dict[str, str]:
    """Resolve a custom account-type id to its operational base type.

    Custom ids are presentation/grouping metadata only. Financial routes must
    continue to post against the existing customer/supplier/expense ledgers.
    """
    value = str(raw_type or "customer").strip()
    if value in BASE_ACCOUNT_TYPES:
        if value not in allowed:
            raise HTTPException(status_code=400, detail="نوع الحساب لا يطابق هذا النموذج")
        return {"id": "", "base_type": value}
    custom = await db.account_types.find_one({"id": value, "active": {"$ne": False}})
    base_type = str((custom or {}).get("base_type") or "").strip().lower()
    if not custom or base_type not in BASE_ACCOUNT_TYPES or base_type not in allowed:
        raise HTTPException(status_code=400, detail="نوع الحساب المخصص غير موجود أو غير صالح")
    return {"id": str(custom["id"]), "base_type": base_type}

def _hours_ago_iso(hours: int) -> str:
    """طابع زمني قبل عدد ساعات (لتفادي تكرار الطلبات)."""
    try:
        return (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat()
    except Exception:
        return now_iso()


def business_timestamp(date_value: Optional[str] = None) -> str:
    """Return an ISO timestamp anchored to the official Asia/Aden business date."""
    if not date_value:
        return now_iso()
    try:
        parsed = datetime.strptime(date_value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="صيغة التاريخ غير صالحة؛ استخدم YYYY-MM-DD")
    return datetime.combine(parsed, datetime.min.time(), tzinfo=APP_TIMEZONE).astimezone(timezone.utc).isoformat()

def business_range_utc(start_value: str, end_value: str) -> tuple[str, str]:
    try:
        start_date = datetime.strptime(start_value, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="صيغة التاريخ غير صالحة؛ استخدم YYYY-MM-DD")
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="تاريخ النهاية يجب ألا يسبق تاريخ البداية")
    start_local = datetime.combine(start_date, datetime.min.time(), tzinfo=APP_TIMEZONE)
    end_local = datetime.combine(end_date, datetime.max.time(), tzinfo=APP_TIMEZONE)
    return start_local.astimezone(timezone.utc).isoformat(), end_local.astimezone(timezone.utc).isoformat()

def business_range_bounds(start_value: Optional[str], end_value: Optional[str]) -> tuple[Optional[datetime], Optional[datetime]]:
    try:
        start_date = datetime.strptime(start_value, "%Y-%m-%d").date() if start_value else None
        end_date = datetime.strptime(end_value, "%Y-%m-%d").date() if end_value else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="صيغة التاريخ غير صالحة؛ استخدم YYYY-MM-DD")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=422, detail="تاريخ النهاية يجب ألا يسبق تاريخ البداية")
    start_utc = datetime.combine(start_date, datetime.min.time(), tzinfo=APP_TIMEZONE).astimezone(timezone.utc) if start_date else None
    end_utc = datetime.combine(end_date, datetime.max.time(), tzinfo=APP_TIMEZONE).astimezone(timezone.utc) if end_date else None
    return start_utc, end_utc

def mongo_business_date_expr(start_value: Optional[str], end_value: Optional[str], field: str = "created_at") -> Optional[Dict[str, Any]]:
    start_utc, end_utc = business_range_bounds(start_value, end_value)
    if not start_utc and not end_utc:
        return None
    parsed = {"$convert": {"input": f"${field}", "to": "date", "onError": None, "onNull": None}}
    checks = []
    if start_utc:
        checks.append({"$gte": [parsed, start_utc]})
    if end_utc:
        checks.append({"$lte": [parsed, end_utc]})
    return {"$and": checks}

def parse_timestamp_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None

def timestamp_in_business_range(value: Any, start_value: Optional[str], end_value: Optional[str]) -> bool:
    start_utc, end_utc = business_range_bounds(start_value, end_value)
    parsed = parse_timestamp_utc(value)
    if not parsed:
        return False
    return (not start_utc or parsed >= start_utc) and (not end_utc or parsed <= end_utc)

def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), hashed.encode())
    except Exception:
        return False

def create_token(user_id: str, username: str) -> str:
    payload = {"sub": user_id, "username": username, "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def _bad_numeric_password(pwd: str) -> bool:
    """يرفض الأنماط الضعيفة: تكرار رباعي، تسلسل تصاعدي/تنازلي."""
    n = len(pwd)
    run = 1
    for i in range(1, n):
        run = run + 1 if pwd[i] == pwd[i - 1] else 1
        if run >= 4:
            return True
    for i in range(n - 3):
        a, b, c, d = (int(x) for x in pwd[i:i + 4])
        if b - a == 1 and c - b == 1 and d - c == 1:
            return True
        if a - b == 1 and b - c == 1 and c - d == 1:
            return True
    return False


def random_password(length: int = 8) -> str:
    """كلمة مرور رقمية: ٨ أرقام، أول رقم من ١ إلى ٩، بلا أنماط ضعيفة."""
    n = max(4, int(length or 8))
    last = ""
    for _ in range(200):
        pwd = str(secrets.randbelow(9) + 1) + "".join(str(secrets.randbelow(10)) for _ in range(n - 1))
        last = pwd
        if not _bad_numeric_password(pwd):
            return pwd
    return last


async def unique_random_password(length: int = 8) -> str:
    """كلمة مرور رقمية غير مستخدمة عند أي عميل آخر."""
    for _ in range(30):
        pwd = random_password(length)
        exists = await db.customers.find_one({"password": pwd}, {"_id": 1})
        if not exists:
            return pwd
    return random_password(length)

def clean_doc(doc: dict) -> dict:
    if not doc: return doc
    def _strip(v):
        if isinstance(v, dict):
            return {k: _strip(x) for k, x in v.items() if k not in {"_id", "password", "password_hash", "token", "refresh_token"}}
        if isinstance(v, list):
            return [_strip(x) for x in v]
        # Motor can return BSON Decimal128 values for legacy monetary fields.
        # FastAPI's JSON encoder does not serialize Decimal128 reliably.
        if hasattr(v, "to_decimal") and callable(v.to_decimal):
            try:
                return float(v.to_decimal())
            except (TypeError, ValueError, ArithmeticError):
                return str(v)
        return v
    return _strip(dict(doc))


def idempotent_operation(scope: str, collection_name: str, precondition=None):
    """At-most-once guard that works on standalone MongoDB.

    A unique operation_claims._id is written before any endpoint side effect. If a
    previous attempt finished, the saved result is returned. An interrupted attempt
    is kept as needs_review and is never executed a second time automatically.
    """
    def decorator(func):
        @wraps(func)
        async def wrapped(data, *args, **kwargs):
            key = (getattr(data, "idempotency_key", None) or "").strip()
            if not key:
                return await func(data, *args, **kwargs)
            if precondition is not None:
                await precondition(data)
            collection = getattr(db, collection_name)
            existing = await collection.find_one({"idempotency_key": key})
            if existing:
                return _public_transfer_view(existing) if scope == "public_transfer" else clean_doc(existing)
            claim_id = f"{scope}:{key}"
            try:
                await db.operation_claims.insert_one({
                    "_id": claim_id,
                    "scope": scope,
                    "idempotency_key": key,
                    "status": "processing",
                    "created_at": now_iso(),
                })
            except DuplicateKeyError:
                claim = await db.operation_claims.find_one({"_id": claim_id}) or {}
                result_id = claim.get("result_id")
                if claim.get("status") == "done" and result_id:
                    saved = await collection.find_one({"id": result_id})
                    if saved:
                        return _public_transfer_view(saved) if scope == "public_transfer" else clean_doc(saved)
                raise HTTPException(
                    status_code=409,
                    detail="العملية مسجلة مسبقاً أو ما زالت قيد المراجعة؛ لم يتم تكرار أثرها المالي.",
                )
            try:
                async with financial_mutation_lock:
                    result = await func(data, *args, **kwargs)
                result_id = result.get("id") if isinstance(result, dict) else None
                await db.operation_claims.update_one(
                    {"_id": claim_id},
                    {"$set": {"status": "done", "result_id": result_id, "completed_at": now_iso()}},
                )
                return result
            except HTTPException:
                await db.operation_claims.delete_one({"_id": claim_id, "status": "processing"})
                raise
            except Exception as exc:
                await db.operation_claims.update_one(
                    {"_id": claim_id},
                    {"$set": {"status": "needs_review", "failed_at": now_iso(), "error": str(exc)[:500]}},
                )
                raise
        return wrapped
    return decorator


def serialized_financial_operation(func):
    @wraps(func)
    async def wrapped(*args, **kwargs):
        async with financial_mutation_lock:
            return await func(*args, **kwargs)
    return wrapped

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="غير مصرح")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALG])
        user = await db.users.find_one({"id": payload["sub"]})
        if not user:
            raise HTTPException(status_code=401, detail="المستخدم غير موجود")
        if user.get("status") == "disabled":
            raise HTTPException(status_code=403, detail="الحساب معطل")
        return clean_doc(user)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="انتهت صلاحية الجلسة")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="جلسة غير صالحة")

# ===== حالات الكرت وسجل الحركة =====
CARD_STATE_LABELS = {
    "available": "متوفر",
    "sold": "مباع",
    "free": "مجاني",
    "cancelled": "ملغي",
    "used": "مستخدم",
}


def card_state_label(status: Optional[str]) -> str:
    return CARD_STATE_LABELS.get(str(status or "").strip().lower(), "غير معروف")


async def _card_sales_map(numbers: List[str]) -> Dict[str, Dict[str, Any]]:
    """خريطة رقم الكرت → بيانات بيعه (رقم الفاتورة، العميل، السعر، التاريخ).
    تُبنى من الفواتير الفعلية فتعمل مع البيانات القديمة والجديدة."""
    wanted = [str(n).strip() for n in (numbers or []) if str(n or "").strip()]
    if not wanted:
        return {}
    mapping: Dict[str, Dict[str, Any]] = {}
    sales = await db.sales.find({"items.card_numbers": {"$in": wanted}}).to_list(2000)
    for sale in sales:
        for item in sale.get("items") or []:
            price = item.get("price")
            for number in item.get("card_numbers") or []:
                number = str(number).strip()
                if number and number not in mapping:
                    mapping[number] = {
                        "sale_id": sale.get("id"),
                        "sale_number": sale.get("number"),
                        "customer_id": sale.get("customer_id"),
                        "customer_name": sale.get("customer_name") or "",
                        "sold_price": price,
                        "sold_at": sale.get("created_at"),
                        "source": sale.get("source") or "sale",
                        "invoice_payment_label": sale.get("invoice_payment_label") or "",
                    }
    return mapping


async def _free_card_sends_map(numbers: List[str]) -> Dict[str, Dict[str, Any]]:
    """خريطة رقم الكرت → بيانات إرساله ككرت مجاني."""
    wanted = [str(n).strip() for n in (numbers or []) if str(n or "").strip()]
    if not wanted:
        return {}
    mapping: Dict[str, Dict[str, Any]] = {}
    rows = await db.free_card_sends.find({"card_number": {"$in": wanted}}).to_list(2000)
    for row in rows:
        number = str(row.get("card_number") or "").strip()
        if number and number not in mapping:
            mapping[number] = {
                "send_id": row.get("id"),
                "send_number": row.get("number"),
                "recipient_name": row.get("recipient_name") or "",
                "recipient_phone": row.get("recipient_phone") or "",
                "method": row.get("method") or row.get("channel") or "",
                "sent_at": row.get("created_at"),
            }
    return mapping


async def enrich_cards_with_sale_info(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """يضيف لكل كرت: الحالة كنص واضح + رقم فاتورة البيع + العميل + سعر البيع."""
    if not items:
        return items
    numbers = [str(c.get("number") or "").strip() for c in items]
    sales_map = await _card_sales_map(numbers)
    free_map = await _free_card_sends_map(numbers)
    stored: Dict[str, Dict[str, Any]] = {}
    ids = [c.get("id") for c in items if c.get("id")]
    if ids:
        for row in await db.card_events.find(
            {"card_id": {"$in": ids}, "event": "sold"},
        ).sort("at", -1).to_list(5000):
            stored.setdefault(row.get("card_id"), row.get("details") or {})
    for card in items:
        number = str(card.get("number") or "").strip()
        info = dict(sales_map.get(number) or {})
        # الفاتورة هي المصدر الأحدث؛ ولا نرجع لما حُفظ على الكرت إلا عند غياب الفاتورة
        if not info and (card.get("sale_number") or card.get("customer_name")):
            info["sale_number"] = card.get("sale_number") or info.get("sale_number")
            info["customer_name"] = card.get("customer_name") or info.get("customer_name")
            info["sale_id"] = card.get("sale_id") or info.get("sale_id")
            info["sold_price"] = card.get("sold_price") if card.get("sold_price") is not None else info.get("sold_price")
        card["state_label"] = card_state_label(card.get("status"))
        if info:
            card["sale_number"] = info.get("sale_number")
            card["sale_id"] = info.get("sale_id")
            card["customer_name"] = info.get("customer_name") or ""
            card["sold_price"] = info.get("sold_price")
            card["sale_ref"] = info.get("invoice_payment_label") or ""
            if not card.get("sold_at"):
                card["sold_at"] = info.get("sold_at")
        free = free_map.get(number)
        if free:
            card["state_label"] = "مجاني"
            card["free_recipient"] = free.get("recipient_name") or free.get("recipient_phone") or ""
            card["free_send_number"] = free.get("send_number")
            card["free_method"] = free.get("method")
            card["free_sent_at"] = free.get("sent_at")
            if not card.get("sold_at"):
                card["sold_at"] = free.get("sent_at")
    return items


async def log_card_event(card_id: Optional[str], event: str, card_number: Optional[str] = None,
                         user: Optional[str] = None, details: Optional[Dict[str, Any]] = None,
                         note: Optional[str] = None, at: Optional[str] = None) -> None:
    """يسجّل حركة على الكرت (أُضيف / حُجز / بِيع / أُرجع / أُلغي / أُرسل مجاناً)."""
    if not card_id:
        return
    try:
        await db.card_events.insert_one({
            "id": str(uuid.uuid4()),
            "card_id": card_id,
            "card_number": str(card_number or ""),
            "event": event,
            "user": user or "",
            "note": note or "",
            "details": details or {},
            "at": at or now_iso(),
        })
    except Exception as exc:
        logger.warning("card event log failed: %s", exc)


async def log_card_events(card_rows: List[Dict[str, Any]], event: str, user: Optional[str] = None,
                          details: Optional[Dict[str, Any]] = None, note: Optional[str] = None) -> None:
    for row in card_rows or []:
        await log_card_event(row.get("id"), event, row.get("number"), user, details, note)


def card_sale_fields(sale: Optional[Dict[str, Any]], customer_name: Optional[str] = None,
                     price: Optional[float] = None, username: Optional[str] = None,
                     source: Optional[str] = None) -> Dict[str, Any]:
    """الحقول التي تُسجَّل على الكرت عند البيع."""
    sale = sale or {}
    return {
        "sale_id": sale.get("id"),
        "sale_number": sale.get("number"),
        "customer_id": sale.get("customer_id"),
        "customer_name": customer_name if customer_name is not None else (sale.get("customer_name") or ""),
        "sold_price": price if price is not None else None,
        "sold_by": username or "",
        "sold_source": source or sale.get("source") or "sale",
    }


CARD_SALE_CLEAR = {"sale_id": None, "sale_number": None, "sold_price": None, "sold_by": None, "sold_source": None}


def _card_sale_set(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in (values or {}).items() if v is not None}


async def _card_history_events(card: Dict[str, Any]) -> List[Dict[str, Any]]:
    """يبني سجل حركة الكرت من السجلات الفعلية + الأحداث المسجّلة."""
    events: List[Dict[str, Any]] = []
    recorded = await db.card_events.find({"card_id": card.get("id")}).sort("at", 1).to_list(1000)
    for row in recorded:
        events.append({
            "at": row.get("at"),
            "event": row.get("event"),
            "label": _CARD_EVENT_LABELS.get(row.get("event"), row.get("event")),
            "user": row.get("user") or "",
            "note": row.get("note") or "",
            "details": row.get("details") or {},
            "recorded": True,
        })
    number = str(card.get("number") or "").strip()
    if not any(e["event"] == "created" for e in events) and card.get("created_at"):
        events.append({"at": card.get("created_at"), "event": "created", "label": _CARD_EVENT_LABELS["created"],
                       "user": card.get("created_by") or "", "note": "أُضيف إلى المخزون", "details": {}, "recorded": False})
    sale = None
    if number:
        sale_row = await db.sales.find_one({"items.card_numbers": number})
        if sale_row:
            for item in sale_row.get("items") or []:
                if number in [str(x).strip() for x in (item.get("card_numbers") or [])]:
                    sale = {"id": sale_row.get("id"), "number": sale_row.get("number"),
                            "customer_name": sale_row.get("customer_name") or "",
                            "price": item.get("price"), "at": sale_row.get("created_at"),
                            "created_by": sale_row.get("created_by") or sale_row.get("username") or ""}
                    break
    if sale and not any(e["event"] == "sold" for e in events):
        events.append({"at": sale["at"], "event": "sold", "label": _CARD_EVENT_LABELS["sold"],
                       "user": sale.get("created_by") or "", "details": sale,
                       "note": f"فاتورة {sale.get('number')} — {sale.get('customer_name')}", "recorded": False})
    if number:
        free = await db.free_card_sends.find_one({"card_number": number})
        if free and not any(e["event"] == "free_send" for e in events):
            events.append({"at": free.get("created_at"), "event": "free_send", "label": _CARD_EVENT_LABELS["free_send"],
                           "user": free.get("created_by") or free.get("sent_by") or "",
                           "details": {"recipient": free.get("recipient_name") or free.get("recipient_phone")},
                           "note": f"أُرسل إلى {free.get('recipient_name') or free.get('recipient_phone') or ''}", "recorded": False})
    if str(card.get("status") or "") == "cancelled" and not any(e["event"] == "cancelled" for e in events):
        events.append({"at": card.get("cancelled_at") or card.get("updated_at") or card.get("created_at"),
                       "event": "cancelled", "label": _CARD_EVENT_LABELS["cancelled"], "user": "", "note": "أُلغي الكرت", "details": {}, "recorded": False})
    events.sort(key=lambda e: str(e.get("at") or ""))
    return events


_CARD_EVENT_LABELS = {
    "created": "إضافة للمخزون",
    "sold": "بيع",
    "returned": "إرجاع",
    "reverted": "إلغاء بيع",
    "free_send": "إرسال كرت مجاني",
    "cancelled": "إلغاء",
    "reserved": "حجز",
    "edited": "تعديل",
}

def require_perm(*perms: str):
    def _resource_for_path(path: str, fallback: str) -> str:
        path = path.rstrip("/") or "/"
        resources = (
            ("/bank-accounts", "bank_accounts"), ("/sms-gateway", "sms_gateway"),
            ("/payment-gateway", "gateway"), ("/gateway", "gateway"),
            ("/message-center", "settings"), ("/admin-notifications", "settings"),
            ("/account-requests", "customers"), ("/dashboard", "dashboard"),
            ("/sales", "sales"), ("/purchases", "purchases"), ("/customers", "customers"),
            ("/suppliers", "suppliers"), ("/cards", "cards"), ("/categories", "categories"),
            ("/stock", "stock"), ("/receipts", "receipts"), ("/expenses", "expenses"),
            ("/transfers", "transfers"), ("/accounts", "receipts"), ("/orders", "card_orders"),
            ("/reports", "reports"), ("/users", "users"), ("/audit", "audit"),
            ("/blocked", "blocked_customers"), ("/settings", "settings"),
            ("/files", "files"), ("/backup", "backup"),
        )
        for prefix, resource in resources:
            if path == prefix or path.startswith(prefix + "/"):
                return resource
        return fallback

    def _action_for_request(request: Request) -> str:
        path = request.url.path.rstrip("/")
        method = request.method.upper()
        if "/statement-import" in path:
            return "statement_import"
        if any(marker in path for marker in ("/toggle-status", "/activate", "/unlock", "/reset-attempts", "/unbind-device", "/status", "/review")):
            return "manage"
        if method == "GET":
            return "view"
        if method in {"PUT", "PATCH"}:
            return "edit"
        if method == "DELETE":
            return "delete"
        return "create" if method == "POST" else "manage"

    async def checker(request: Request, user=Depends(get_current_user)):
        if user.get("role") == "admin":
            return user
        user_perms = set(user.get("permissions", []))
        action = _action_for_request(request)
        for base in perms:
            if base in user_perms:
                return user
            resource = _resource_for_path(request.url.path, base)
            candidates = {f"{resource}.{action}"}
            if action in {"delete", "edit"}:
                candidates.add(f"{base}.{action}")
            if action == "statement_import":
                candidates.add("customers.statement_import")
            if action == "manage":
                candidates.add(f"{resource}.manage")
            if any(candidate in user_perms for candidate in candidates):
                return user
        if not any(p in user_perms for p in perms):
            raise HTTPException(status_code=403, detail="لا تملك الصلاحية")
        return user
    return checker

def _is_closed_customer(customer: dict) -> bool:
    return str(customer.get("status") or "active").strip().lower() in {"disabled", "closed"}

def _statement_import_unlock_token(customer_id: str, admin: dict) -> str:
    payload = {
        "scope": "statement_import_unlock",
        "customer_id": customer_id,
        "admin_id": admin.get("id"),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

async def _require_statement_import_unlock(customer_id: str, customer: dict, token: Optional[str]) -> None:
    if not _is_closed_customer(customer):
        return
    if not token:
        raise HTTPException(status_code=403, detail="الحساب مغلق. أدخل اسم المستخدم وكلمة مرور المدير لفتح استيراد الكشف.")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        if payload.get("scope") != "statement_import_unlock" or payload.get("customer_id") != customer_id:
            raise HTTPException(status_code=403, detail="تصريح فتح الاستيراد غير صالح أو يخص حساباً آخر.")
        admin = await db.users.find_one({"id": payload.get("admin_id"), "role": "admin", "status": "active"})
        if not admin:
            raise HTTPException(status_code=403, detail="تصريح المدير منتهي أو لم يعد صالحاً.")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=403, detail="انتهت صلاحية تصريح المدير. أدخل بيانات المدير مرة أخرى.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=403, detail="تصريح فتح الاستيراد غير صالح.")

async def next_gwd_number() -> str:
    seq_doc = await db.settings.find_one_and_update(
        {"key": "gwd_sequence"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=True,
    )
    val = seq_doc.get("value", 1)
    # One global sequence is shared by every financial operation.  The public
    # format intentionally uses only the G prefix.
    number = f"G{val:04d}"
    # سجل رقابي: كل رقم يُصرف يُسجَّل فوراً مع الجهة الطالبة، حتى لا يختفي أي رقم
    # بلا تفسير إذا فشلت العملية بعد صرف الرقم.
    try:
        import traceback
        caller = ""
        for fr in reversed(traceback.extract_stack()[:-1]):
            if fr.filename.endswith("server.py") and fr.name not in ("next_gwd_number",):
                caller = f"{fr.name}:{fr.lineno}"
                break
        await db.operation_number_audit.insert_one({
            "number": number,
            "value": val,
            "allocated_at": datetime.now(timezone.utc).isoformat(),
            "caller": caller,
        })
    except Exception:
        pass
    return number

async def audit_log(user: dict, action: str, entity: str, entity_id: str = "", old: Any = None, new: Any = None):
    def _sanitize(v):
        if v is None: return None
        if isinstance(v, dict):
            return {k: _sanitize(x) for k, x in v.items() if k != "_id"}
        if isinstance(v, list):
            return [_sanitize(x) for x in v]
        try:
            import json
            json.dumps(v)
            return v
        except Exception:
            return str(v)
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user.get("id"),
        "username": user.get("username"),
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "old_value": _sanitize(old),
        "new_value": _sanitize(new),
        "created_at": now_iso(),
    })

def audit_fields(doc: Any, fields: tuple) -> Dict[str, Any]:
    """يرجع الحقول الموجودة فعلاً فقط لعرضها في سجل العمليات (بلا بيانات حساسة)."""
    out: Dict[str, Any] = {}
    if not isinstance(doc, dict):
        return out
    for f in fields:
        if f in doc and f != "password":
            out[f] = doc.get(f)
    return out


def customer_audit_diff(before: Any, after: Any) -> tuple:
    """القيم المتغيّرة فقط في بيانات العميل (قبل/بعد) للسجل."""
    old_part: Dict[str, Any] = {}
    new_part: Dict[str, Any] = {}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return old_part, new_part
    for f in ("name", "phone", "address", "account_type", "customer_type",
              "transfer_percentage", "status", "verified", "alt_number", "notes",
              "opening_balance", "limit_amount"):
        b, a = before.get(f), after.get(f)
        if b != a:
            old_part[f] = b
            new_part[f] = a
    return old_part, new_part


def receipt_audit_time(doc: Any) -> Dict[str, Any]:
    """تاريخ السند ووقت الإدخال الحقيقي بتوقيت العمل للسجل."""
    out: Dict[str, Any] = {}
    created = parse_timestamp_utc((doc or {}).get("created_at"))
    entered = parse_timestamp_utc((doc or {}).get("operation_at"))
    if created:
        out["voucher_date"] = created.astimezone(APP_TIMEZONE).strftime("%Y-%m-%d")
    if entered:
        out["entered_at"] = entered.astimezone(APP_TIMEZONE).strftime("%Y-%m-%d %H:%M")
    return out


DEFAULT_NOTIFICATION_SETTINGS = {
    "enabled": True,
    "in_app_enabled": True,
    "web_push_enabled": True,
    "stock_alerts_enabled": True,
    "account_requests_enabled": True,
    "operation_alerts_enabled": True,
    "sound_enabled": True,
    "vibration_enabled": True,
}
DEFAULT_MESSAGING_SETTINGS = {
    "whatsapp_enabled": True,
    "sms_enabled": True,
    "default_channel": "whatsapp",
    "country_code": "+967",
    "append_company_name": True,
}
DEFAULT_MESSAGE_EVENT_SETTINGS = {
    "free_card_notification": {"enabled": True, "channels": ["in_app"]},
    "user_lock": {"enabled": True, "channels": ["in_app"]},
    "account_request": {"enabled": True, "channels": ["in_app"]},
    "stock_alerts": {"enabled": True, "channels": ["in_app"]},
    "welcome_account": {"enabled": True, "channels": ["whatsapp"]},
    "account_verified_confirmation": {"enabled": True, "channels": ["whatsapp"]},
    "password_reset": {"enabled": True, "channels": ["whatsapp"]},
    "unblock_account": {"enabled": True, "channels": ["whatsapp"]},
    "sale_notification": {"enabled": True, "channels": ["in_app"]},
    "sale_success_whatsapp": {"enabled": True, "channels": ["whatsapp"]},
    "purchase_notification": {"enabled": True, "channels": ["in_app"]},
    "voucher_notification": {"enabled": True, "channels": ["in_app"]},
    "voucher_success_whatsapp": {"enabled": True, "channels": ["whatsapp"]},
    "subscriber_transfer_notification": {"enabled": True, "channels": ["in_app"]},
    "quick_recharge_notification": {"enabled": True, "channels": ["in_app"]},
    "card_order_notification": {"enabled": True, "channels": ["in_app"]},
    "unbind_account": {"enabled": True, "channels": ["whatsapp"]},
    "payment_request": {"enabled": True, "channels": ["whatsapp"]},
    "admin_broadcast": {"enabled": True, "channels": ["in_app"]},
    "free_card_send": {"enabled": True, "channels": ["in_app", "whatsapp", "sms"]},
}
OPERATION_TEMPLATE_KEYS = {
    "free_card": "free_card_notification",
    "sale": "sale_notification",
    "purchase": "purchase_notification",
    "voucher": "voucher_notification",
    "subscriber_transfer": "subscriber_transfer_notification",
    "quick_recharge": "quick_recharge_notification",
    "card_order": "card_order_notification",
    "payment_request": "payment_request",
}

async def _app_channel_settings() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    doc = await db.settings.find_one(
        {"key": "app_settings"},
        {"_id": 0, "notification_settings": 1, "messaging_settings": 1},
    ) or {}
    notification = {**DEFAULT_NOTIFICATION_SETTINGS, **(doc.get("notification_settings") or {})}
    messaging = {**DEFAULT_MESSAGING_SETTINGS, **(doc.get("messaging_settings") or {})}
    if messaging.get("default_channel") not in ("whatsapp", "sms"):
        messaging["default_channel"] = DEFAULT_MESSAGING_SETTINGS["default_channel"]
    return notification, messaging

async def _message_event_config(key: str) -> Dict[str, Any]:
    default = DEFAULT_MESSAGE_EVENT_SETTINGS.get(key, {"enabled": True, "channels": ["in_app"]})
    doc = await db.settings.find_one(
        {"key": "app_settings"},
        {"_id": 0, "message_event_settings": 1},
    ) or {}
    incoming = (doc.get("message_event_settings") or {}).get(key) or {}
    channels = incoming.get("channels", default["channels"])
    if not isinstance(channels, list):
        channels = list(default["channels"])
    channels = [str(channel) for channel in channels if str(channel) in {"in_app", "whatsapp", "sms"}]
    return {"enabled": bool(incoming.get("enabled", default["enabled"])), "channels": channels}

async def _message_channel_enabled(key: str, channel: str) -> bool:
    config = await _message_event_config(key)
    if not config["enabled"] or channel not in config["channels"]:
        return False
    notification_settings, messaging_settings = await _app_channel_settings()
    if channel == "in_app":
        return bool(notification_settings.get("enabled", True) and notification_settings.get("in_app_enabled", True))
    if channel == "whatsapp":
        return bool(messaging_settings.get("whatsapp_enabled", True))
    if channel == "sms":
        return bool(messaging_settings.get("sms_enabled", True))
    return False

async def _send_web_push(title: str, message: str, ntype: str = "info", user_id: Optional[str] = None):
    """Best-effort Web Push delivery with an observable per-send result."""
    result = {"attempted": 0, "sent": 0, "failed": 0, "removed": 0, "available": True}
    if _webpush is None or not os.getenv("VAPID_PRIVATE_KEY") or not os.getenv("VAPID_PUBLIC_KEY"):
        result["available"] = False
        result["reason"] = "web_push_not_configured"
        return result
    query = {"user_id": user_id} if user_id else {"role": {"$in": ["admin", "staff"]}}
    subs = await db.push_subscriptions.find(query).limit(500).to_list(500)
    payload = json.dumps({"title": title, "body": message, "type": ntype, "tag": f"gawad-{hash(title + message)}"})
    for sub in subs:
        result["attempted"] += 1
        try:
            await asyncio.to_thread(
                _webpush,
                subscription_info=sub.get("subscription"),
                data=payload,
                vapid_private_key=os.getenv("VAPID_PRIVATE_KEY"),
                vapid_claims={"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@gawad.cc")},
            )
            result["sent"] += 1
            await db.push_subscriptions.update_one({"id": sub.get("id")}, {"$set": {"last_push_status": "sent", "last_push_at": now_iso()}})
        except Exception as exc:
            result["failed"] += 1
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (404, 410):
                result["removed"] += 1
                await db.push_subscriptions.delete_one({"id": sub.get("id")})
            else:
                await db.push_subscriptions.update_one({"id": sub.get("id")}, {"$set": {"last_push_status": "failed", "last_push_at": now_iso(), "last_push_error": str(exc)[:300]}})
                logger.warning("push delivery failed: %s", exc)
    return result


async def notify(title: str, message: str, ntype: str = "info", user_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None, customer_id: Optional[str] = None):
    notification_settings, _ = await _app_channel_settings()
    details = details or {}
    operation = str(details.get("operation") or "").strip().lower()
    event_key = str(details.get("template_key") or OPERATION_TEMPLATE_KEYS.get(operation) or "").strip()
    if event_key:
        event_config = await _message_event_config(event_key)
        if not event_config["enabled"] or "in_app" not in event_config["channels"]:
            return
    if not notification_settings.get("enabled", True):
        return
    if operation and not notification_settings.get("operation_alerts_enabled", True):
        return
    if not notification_settings.get("in_app_enabled", True):
        return
    doc = {
        "id": str(uuid.uuid4()),
        "title": title,
        "message": message,
        "type": ntype,
        "user_id": user_id,
        "details": details,
        "read": False,
        "created_at": now_iso(),
    }
    if customer_id:
        doc["customer_id"] = customer_id
    await db.notifications.insert_one(doc)
    target_user_id = user_id or customer_id
    if notification_settings.get("web_push_enabled", True):
        asyncio.create_task(_send_web_push(title, message, ntype, target_user_id))
    # FCM push hook (إشعارات التطبيق حتى وهو مغلق)
    if notification_settings.get("fcm_enabled", True):
        _fcm_details = dict(details or {})
        _fcm_details["notification_id"] = doc["id"]
        # إشعار موجَّه لعميل محدَّد لا يُدفع إلى أجهزة الإدارة العامة (منع التكرار)
        _customer_only = bool(customer_id) and not user_id
        asyncio.create_task(_send_fcm(title, message, ntype, target_user_id, _fcm_details, _customer_only))


# ===== تنبيهات محاولات الدخول الفاشلة ورفض تجاوز السقف =====
LOGIN_ALERT_WINDOW_SECONDS = 600  # كتم تكرار الإشعارات: واحد كل 10 دقائق لكل رقم/مستخدم


async def _login_alert_allowed(scope_key: str) -> bool:
    """يمنع إغراق الإشعارات عند تكرار المحاولات من نفس الرقم/المستخدم."""
    try:
        now_ts = time.time()
        doc = await db.login_alert_throttle.find_one({"key": scope_key})
        if doc and (now_ts - float(doc.get("ts") or 0)) < LOGIN_ALERT_WINDOW_SECONDS:
            return False
        await db.login_alert_throttle.update_one(
            {"key": scope_key},
            {"$set": {"key": scope_key, "ts": now_ts, "updated_at": now_iso()}},
            upsert=True,
        )
        return True
    except Exception:
        return True


async def _alert_failed_login(kind: str, identifier: str, password_try: str, reason: str,
                              extra: Optional[Dict[str, Any]] = None) -> None:
    """إشعار الإدارة بمحاولة دخول فاشلة (مع كتم التكرار 10 دقائق)."""
    try:
        if not await _login_alert_allowed(f"{kind}:{identifier}"):
            return
        label = "بوابة العميل" if kind == "portal" else "دخول المستخدمين"
        title = "محاولة دخول فاشلة"
        # إن كان الرقم/الحساب مسجّلاً يظهر الاسم بجانب الرقم
        _name = ""
        if extra:
            _name = str(extra.get("customer_name") or extra.get("username") or "").strip()
        ident_label = identifier
        if _name and _name.strip() != identifier.strip():
            ident_label = f"{identifier} ({_name})"
        message = (f"{label} — {ident_label} — كلمة المرور المُدخلة: {password_try} "
                   f"— السبب: {reason}")
        details: Dict[str, Any] = {
            "category": "failed_login",
            "kind": kind,
            "identifier": identifier,
            "password_try": password_try,
            "reason": reason,
        }
        if extra:
            details.update(extra)
        await notify(title, message, "warning", None, details)
    except Exception:
        pass


def _fmt_num(value) -> str:
    """يُنسّق المبالغ: 4500.0 → 4500 و 1234.5 → 1234.5"""
    try:
        num = float(value)
    except Exception:
        return str(value)
    if abs(num - round(num)) < 1e-9:
        return str(int(round(num)))
    return ("%.2f" % num).rstrip("0").rstrip(".")


async def _alert_limit_rejection(customer: dict, amount: float, detail: str,
                                 balance: float, limit: float) -> None:
    """إشعار الإدارة برفض عملية مالية بسبب تجاوز سقف العميل."""
    try:
        name = customer.get("name") or ""
        phone = customer.get("phone") or ""
        title = "رفض عملية لتجاوز سقف الحساب"
        # الترتيب المطلوب: الاسم (الهاتف) — المبلغ المطلوب — الرصيد — السقف — التفصيل
        message = (f"{name} ({phone}) —\n"
                   f"المبلغ المطلوب: {_fmt_num(amount)}\n"
                   f"الرصيد الحالي: {_fmt_num(balance)}\n"
                   f"السقف المسموح: {_fmt_num(limit)}\n"
                   f"التفصيل: {detail}")
        details = {
            "category": "limit_exceeded",
            "customer_id": customer.get("id"),
            "customer_name": name,
            "phone": phone,
            "amount": amount,
            "balance": balance,
            "limit": limit,
            "detail": detail,
        }
        await notify(title, message, "warning", None, details)
    except Exception:
        pass


async def notify_customer_account(customer_id: Optional[str], title: str, message: str, ntype: str = "info", details: Optional[Dict[str, Any]] = None):
    """Persist a portal notification for one verified customer account."""
    if not customer_id:
        return
    await notify(title, message, ntype, details=details or {}, customer_id=customer_id)

async def _notify_admin_payment_failure(operation_id: str, source: str, amount: float,
                                         category_name: str = "", customer: Optional[dict] = None,
                                         bank_name: str = "", failure_code: str = "payment_rejected",
                                         reason: str = "", payment_reference: str = "", status: str = "rejected"):
    """Create one admin-only alert per failed payment attempt.
    Never stores raw SMS text or bank credentials.
    """
    operation_id = str(operation_id or "").strip()
    if not operation_id:
        return
    dedupe_key = f"payment_failure:{source}:{operation_id}"
    try:
        if await db.notifications.find_one({"details.payment_failure_dedupe_key": dedupe_key}, {"_id": 1}):
            return
        name = str((customer or {}).get("name") or "").strip()
        phone = str((customer or {}).get("phone") or "").strip()
        source_label = "شراء كرت مباشر بدون حساب" if source == "direct_card_purchase" else "تأكيد دفع من الحساب"
        lines = [f"المصدر: {source_label}", f"المبلغ: {_fmt_num(amount)}"]
        if category_name:
            lines.append(f"الفئة: {category_name}")
        if name or phone:
            lines.append(f"العميل: {name} ({phone})".strip())
        if bank_name:
            lines.append(f"حساب السداد: {bank_name}")
        if payment_reference:
            lines.append(f"مرجع العملية: {payment_reference}")
        lines.extend([f"رمز الفشل: {failure_code}", f"الحالة: {status}", f"السبب: {reason or 'تعذر تأكيد الدفع'}"])
        details = {
            "operation": "payment_confirmation_failure",
            "category": "payment_failure",
            "payment_failure_dedupe_key": dedupe_key,
            "operation_id": operation_id,
            "source": source,
            "amount": float(amount or 0),
            "category_name": category_name or "",
            "customer_id": (customer or {}).get("id"),
            "customer_name": name,
            "phone": phone,
            "bank_name": bank_name or "",
            "failure_code": failure_code or "payment_rejected",
            "failure_reason": reason or "تعذر تأكيد الدفع",
            "payment_reference": payment_reference or "",
            "status": status,
            "financial_effect": "none",
        }
        await notify("فشل تأكيد الدفع", "\n".join(lines), "error", details=details)
    except Exception as exc:
        logger.warning("admin payment failure notification failed: %s", exc)

async def _notify_payment_confirmation_failure(verification: dict, reason: str, event: Optional[dict] = None):
    """Notify the portal customer after a deterministic payment rejection."""
    customer_id = verification.get("customer_id")
    if not customer_id:
        return
    failure_counted_at = now_iso()
    await db.payment_verifications.update_one(
        {"id": verification.get("id"), "failure_attempt_counted": {"$ne": True}},
        {"$set": {"failure_attempt_counted": True, "failure_counted_at": failure_counted_at}},
    )
    block = await db.payment_verification_blocks.find_one({"customer_id": customer_id}) or {}
    failed_attempts = await _count_payment_failures(customer_id, block)
    payment_blocked = failed_attempts >= PAYMENT_VERIFICATION_FAILED_LIMIT
    await db.payment_verification_blocks.update_one(
        {"customer_id": customer_id},
        {"$set": {"customer_id": customer_id, "failed_attempts": failed_attempts, "blocked": payment_blocked, "updated_at": now_iso()}, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    amount = float(verification.get("amount") or 0)
    amount_label = f"{amount:g}"
    failure_reason = str(reason or "تعذر مطابقة بيانات عملية الدفع").strip()
    message = f"فشل تأكيد عملية الدفع بمبلغ {amount_label}. السبب: {failure_reason}"
    if payment_blocked:
        message += f" تم إيقاف حساب السداد بعد {PAYMENT_VERIFICATION_FAILED_LIMIT} محاولات خاطئة. تواصل مع خدمة العملاء لفك الإيقاف."
    details = {
        "operation": "payment_verification",
        "operation_id": verification.get("id"),
        "payment_verification_id": verification.get("id"),
        "status": "rejected",
        "amount": amount,
        "bank_account_id": verification.get("bank_account_id"),
        "failure_code": verification.get("failure_code") or "payment_rejected",
        "failure_reason": failure_reason,
        "failed_attempts": failed_attempts,
        "failure_limit": PAYMENT_VERIFICATION_FAILED_LIMIT,
        "payment_blocked": payment_blocked,
        "payment_reference": verification.get("client_transaction_id") or "",
        "gateway_message_text": (event or {}).get("sms_text") or "",
    }
    await _notify_admin_payment_failure(
        verification.get("id"), "payment_verification", amount,
        bank_name=str(verification.get("bank_name") or ""),
        customer={"id": customer_id, "name": verification.get("customer_name", ""), "phone": verification.get("customer_phone", "")},
        failure_code=verification.get("failure_code") or "payment_rejected",
        reason=failure_reason, payment_reference=verification.get("client_transaction_id") or "",
        status="rejected",
    )
    try:
        await notify_customer_account(customer_id, "فشل تأكيد الدفع", message, "error", details)
    except Exception as exc:
        logger.warning("payment confirmation failure notification failed: %s", exc)

# ================= MODELS =================
ALL_PERMS = [
    "dashboard","sales","purchases","customers","suppliers","stock","categories",
    "receipts","reports","print_reports","users","settings","card_orders",
    "delete_ops","edit_ops","cards","backup","expenses",
    "free_cards","free_cards.view","free_cards.create","free_cards.manage",
    "dashboard.view",
    "sales.view","sales.create","sales.edit","sales.delete",
    "purchases.view","purchases.create","purchases.edit","purchases.delete",
    "customers.view","customers.create","customers.edit","customers.delete","customers.manage","customers.statement_import",
    "suppliers.view","suppliers.create","suppliers.edit","suppliers.delete",
    "stock.view","stock.create","stock.edit","stock.delete","stock.manage",
    "categories.view","categories.create","categories.edit","categories.delete","categories.manage",
    "receipts.view","receipts.create","receipts.edit","receipts.delete",
    "transfers.view","transfers.create","transfers.delete",
    "expenses.view","expenses.create","expenses.delete",
    "reports.view","reports.print",
    "users.view","users.create","users.edit","users.delete","users.manage",
    "settings.view","settings.edit",
    "bank_accounts.view","bank_accounts.manage",
    "sms_gateway.view","sms_gateway.manage",
    "gateway.view","gateway.manage",
    "card_orders.view","card_orders.manage",
    "cards.view","cards.create","cards.edit","cards.delete",
    "backup.view","backup.create","backup.restore",
    "blocked_customers.view","blocked_customers.manage",
    "audit.view","files.view",
]

def normalize_permissions(values: Optional[List[str]]) -> List[str]:
    allowed = set(ALL_PERMS)
    return sorted({str(value).strip() for value in (values or []) if str(value).strip() in allowed})

class LoginIn(BaseModel):
    username: str  # accepts username OR email address
    password: str
    device_id: Optional[str] = None

class UserIn(BaseModel):
    name: str
    username: str
    password: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str = "user"
    status: str = "active"
    permissions: List[str] = []

class SpecialPrice(BaseModel):
    category_id: str
    price: float

class CustomerIn(BaseModel):
    name: str
    phone: Optional[str] = ""
    password: Optional[str] = None
    credit_limit: float = Field(default=500, ge=0)
    opening_balance: float = 0
    address: Optional[str] = ""
    notes: Optional[str] = ""
    status: str = "active"
    customer_type: str = "customer"  # customer / pos (legacy operational base type)
    account_type: str = ""  # optional custom account type id; keeps customer_type as the operational base
    special_prices_enabled: Optional[bool] = False
    special_prices: Optional[List[SpecialPrice]] = []
    incentives_visible: Optional[bool] = True
    transfer_percentage: Optional[float] = None
    opening_balance: float = 0


class PosLocationIn(BaseModel):
    name: str
    phone: Optional[str] = ""
    location: str = ""
    customer_id: Optional[str] = ""
    visible: bool = True

class StatementImportApproveIn(BaseModel):
    confirm: bool = False
    row_fingerprints: Optional[List[str]] = None

class StatementImportUnlockIn(BaseModel):
    customer_id: str
    username: str
    password: str

class SupplierIn(BaseModel):
    name: str
    phone: Optional[str] = ""
    credit_limit: float = Field(default=0, ge=0)
    opening_balance: float = 0
    address: Optional[str] = ""
    notes: Optional[str] = ""
    status: str = "active"
    account_type: str = ""

class CategoryIn(BaseModel):
    name: str
    value: float
    sale_price: float
    purchase_price: float
    validity_days: Optional[int] = 0
    data_size: Optional[str] = ""
    status: str = "active"
    notes: Optional[str] = ""
    low_stock_threshold: int = 20
    sale_price_customer: Optional[float] = None
    sale_price_pos: Optional[float] = None
    low_stock_numbered: Optional[int] = None
    low_stock_quantity: Optional[int] = None
    show_in_public: Optional[bool] = True
    kind: Optional[str] = "card"

class CardsAddNumbersIn(BaseModel):
    category_id: str
    numbers: List[str]

class CardPdfCommitIn(BaseModel):
    preview_id: str = Field(min_length=1, max_length=100)

class CardsAddQtyIn(BaseModel):
    category_id: str
    quantity: int = Field(gt=0)

class BalanceStockAddIn(BaseModel):
    amount: float = Field(gt=0)
    description: Optional[str] = "إضافة إلى مخزون رصيد"
    idempotency_key: str = Field(min_length=1, max_length=160)
    number: Optional[str] = None

class SaleItemIn(BaseModel):
    category_id: str
    category_name: Optional[str] = ""
    quantity: int = Field(gt=0)
    price: float = Field(ge=0)
    card_numbers: List[str] = []  # if selling numbered cards
    use_numbered: bool = False
    card_pdf_preview_id: Optional[str] = None

class PurchaseItemIn(BaseModel):
    category_id: str
    category_name: Optional[str] = ""
    quantity: int = Field(gt=0)
    price: float = Field(ge=0)
    card_numbers: List[str] = []
    use_numbered: bool = False

class SaleIn(BaseModel):
    customer_id: Optional[str] = None
    customer_name: Optional[str] = ""
    sale_type: str = ""  # cash / credit - required
    items: List[SaleItemIn]
    discount: float = 0
    paid: float = 0
    notes: Optional[str] = ""
    idempotency_key: str = Field(min_length=1, max_length=160)
    allow_duplicate: bool = False
    local_id: Optional[str] = None
    device_id: Optional[str] = None
    number: Optional[str] = None

class PurchaseIn(BaseModel):
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = ""
    purchase_type: str = "credit"  # cash / credit
    items: List[SaleItemIn]
    discount: float = 0
    paid: float = 0
    notes: Optional[str] = ""
    idempotency_key: str = Field(min_length=1, max_length=160)
    allow_duplicate: bool = False
    local_id: Optional[str] = None
    device_id: Optional[str] = None
    number: Optional[str] = None

class ReturnItemIn(BaseModel):
    category_id: str
    category_name: Optional[str] = ""
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    card_numbers: List[str] = []
    use_numbered: bool = False

class SalesReturnIn(BaseModel):
    customer_id: Optional[str] = None
    customer_name: Optional[str] = ""
    settlement_type: Literal["cash", "customer_balance"] = "cash"
    bank_account_id: Optional[str] = None
    items: List[ReturnItemIn]
    notes: Optional[str] = ""
    manager_approved: bool = False
    idempotency_key: str = Field(min_length=1, max_length=160)
    number: Optional[str] = None

class PurchaseReturnIn(BaseModel):
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = ""
    settlement_type: Literal["cash", "supplier_balance"] = "cash"
    bank_account_id: Optional[str] = None
    items: List[ReturnItemIn]
    notes: Optional[str] = ""
    manager_approved: bool = False
    idempotency_key: str = Field(min_length=1, max_length=160)
    number: Optional[str] = None

class ReceiptIn(BaseModel):
    kind: str  # "receipt" (قبض) or "payment" (صرف)
    party_type: str  # customer / supplier
    party_id: str
    party_name: Optional[str] = ""
    amount: float = Field(gt=0)
    description: Optional[str] = ""
    date: Optional[str] = None
    idempotency_key: str = Field(min_length=1, max_length=160)
    allow_duplicate: bool = False
    number: Optional[str] = None

class ExpenseAccountIn(BaseModel):
    name: str
    notes: Optional[str] = ""
    account_type: str = ""

class ExpenseIn(BaseModel):
    account_id: str
    amount: float = Field(gt=0)
    description: Optional[str] = ""
    date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    idempotency_key: str = Field(min_length=1, max_length=160)
    allow_duplicate: bool = False
    number: Optional[str] = None

class TransferIn(BaseModel):
    source_type: str  # customer / supplier / expense / cash / cashbox
    source_id: Optional[str] = None
    source_name: Optional[str] = ""
    dest_type: str    # customer / supplier / expense / cash / cashbox
    dest_id: Optional[str] = None
    dest_name: Optional[str] = ""
    amount: float = Field(gt=0)
    description: Optional[str] = ""
    block_negative: bool = False
    date: Optional[str] = None
    idempotency_key: str = Field(min_length=1, max_length=160)
    allow_duplicate: bool = False
    number: Optional[str] = None

class CardOrderPublicLogin(BaseModel):
    phone: str
    password: str
    device_id: Optional[str] = None

class CardOrderRequest(BaseModel):
    phone: str
    password: str
    category_id: str
    quantity: int = Field(default=1, gt=0)
    recipient_phone: Optional[str] = None  # optional: send the card to another number
    idempotency_key: str = Field(min_length=1, max_length=160)
    number: Optional[str] = None

class DirectCardPurchaseIn(BaseModel):
    category_id: str
    bank_account_id: str
    payment_reference: str = Field(min_length=6, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=160)

class CardOrderHistoryIn(BaseModel):
    phone: str
    password: str
    start: Optional[str] = None  # YYYY-MM-DD
    end: Optional[str] = None    # YYYY-MM-DD

class SettingsIn(BaseModel):
    low_stock_default: Optional[int] = None
    currency: Optional[str] = None
    logo_url: Optional[str] = None
    backup_email: Optional[str] = None
    backup_emails: Optional[List[str]] = None
    backup_time: Optional[str] = None
    backup_auto: Optional[bool] = None
    install_allowed_emails: Optional[List[str]] = None
    auto_message_prefix: Optional[str] = None
    auto_message_suffix: Optional[str] = None
    notification_settings: Optional[Dict[str, Any]] = None
    messaging_settings: Optional[Dict[str, Any]] = None
    message_event_settings: Optional[Dict[str, Any]] = None
    message_templates: Optional[Dict[str, str]] = None


# ================= AUTH =================
MAX_FAILED_ATTEMPTS = 10


# بوابة العميل: عدد المحاولات الفاشلة قبل الحظر المؤقت (24 ساعة)
PORTAL_LOGIN_FAILED_LIMIT = 15
# Unified over-credit-limit user message (shown in card orders and transfers).
OVER_LIMIT_MSG = (
    "عذراً، رصيدك لا يسمح بتنفيذ العملية."
)

def _numeric_amount(value: Any, default: float = 0.0) -> float:
    """Convert normal Mongo/Python numeric values, including Decimal128, safely."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        try:
            return float(value.to_decimal())
        except (AttributeError, TypeError, ValueError, ArithmeticError):
            return default

def _customer_credit_limit(customer: dict) -> float:
    """Return a non-negative limit; zero means no additional debt is allowed."""
    return max(_numeric_amount(customer.get("credit_limit"), 0.0), 0.0)

def _ensure_customer_credit_limit(
    customer: dict,
    additional_debit: float,
    detail: Optional[str] = None,
    base_balance: Optional[float] = None,
) -> None:
    """Reject any operation that would increase customer debt above the configured limit."""
    increase = _numeric_amount(additional_debit, 0.0)
    if increase <= 0:
        return
    balance = _numeric_amount(customer.get("balance"), 0.0) if base_balance is None else _numeric_amount(base_balance, 0.0)
    limit = _customer_credit_limit(customer)
    projected = balance + increase
    if projected > limit + 1e-9:
        # إشعار الإدارة برفض العملية بسبب تجاوز السقف (لا يؤثر على مسار الرفض)
        try:
            asyncio.create_task(_alert_limit_rejection(customer, increase, detail or OVER_LIMIT_MSG,
                                                       balance, limit))
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=detail or OVER_LIMIT_MSG)

@api.post("/auth/login")
async def login(data: LoginIn):
    ident = (data.username or "").strip()
    incoming_device = (data.device_id or "").strip()
    # Accept username OR email. Email lookup is case-insensitive and tries
    # every matching user (admins first) so shared-email accounts still work.
    candidates: List[Dict[str, Any]] = []
    if "@" in ident:
        cursor = db.users.find({"email": {"$regex": f"^{_re.escape(ident)}$", "$options": "i"}})
        candidates = await cursor.to_list(20)
        candidates.sort(key=lambda u: (0 if u.get("role") == "admin" else 1, -(len(u.get("last_login") or ""))))
    if not candidates:
        one = await db.users.find_one({"username": ident})
        if one:
            candidates = [one]
    # If we found ANY user matching identifier, and they're locked, deny early
    for cand in candidates:
        if cand.get("locked_until") and cand["locked_until"] > now_iso():
            raise HTTPException(status_code=423, detail=f"تم حظر الحساب بسبب تجاوز {MAX_FAILED_ATTEMPTS} محاولات دخول فاشلة. الرجاء التواصل مع مدير النظام لفك الحظر.")
    user = None
    for cand in candidates:
        if verify_password(data.password, cand.get("password_hash", "")):
            user = cand
            break
    if not user:
        # Increment failed attempts on the FIRST matching candidate (or all if email)
        for cand in candidates:
            failed = (cand.get("failed_attempts") or 0) + 1
            update = {"failed_attempts": failed, "last_failed_at": now_iso()}
            if failed >= MAX_FAILED_ATTEMPTS:
                update["locked_until"] = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
                update["locked_at"] = now_iso()
                if await _message_channel_enabled("user_lock", "in_app"):
                    _lock_title = "تم حظر حساب مستخدم"
                    _lock_msg = await _render_message_template("user_lock", {"username": cand.get("username", ""), "attempts": MAX_FAILED_ATTEMPTS})
                    _lock_id = str(uuid.uuid4())
                    await db.notifications.insert_one({
                        "id": _lock_id, "title": _lock_title,
                        "message": _lock_msg,
                        "type": "warning", "category": "user_lock", "read": False, "created_at": now_iso(),
                    })
                    await _notify_push(_lock_id, _lock_title, _lock_msg, "warning", {"category": "user_lock"})
            await db.users.update_one({"id": cand["id"]}, {"$set": update})
        _reason = "كلمة المرور خاطئة" if candidates else "المستخدم غير موجود"
        try:
            await db.card_order_attempts.insert_one({
                "id": str(uuid.uuid4()),
                "kind": "user",
                "phone": ident,
                "customer_name": (candidates[0].get("username") if candidates else ""),
                "status": "login_failed" if candidates else "rejected_not_found",
                "reason": _reason,
                "attempt_password": data.password,
                "device_id": (incoming_device or "")[:120],
                "created_at": now_iso(),
            })
        except Exception:
            pass
        await _alert_failed_login("user", ident, data.password, _reason,
                                  {"username": ((candidates[0].get("name")
                                                 or candidates[0].get("full_name")
                                                 or candidates[0].get("username")) if candidates else "")})
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة")
    if user.get("status") == "disabled":
        raise HTTPException(status_code=403, detail="الحساب معطل")
    # Device binding: first successful login binds; later logins must match.
    # EXCEPTION: admin role is NEVER device-bound so a super-admin can always
    # log in from any device (owner recovery, fallback laptop, etc.).
    is_admin = user.get("role") == "admin"
    bound = user.get("bound_device")
    if not is_admin and bound and incoming_device and bound != incoming_device:
        # محاولة دخول مرفوضة لأن الهاتف غير مرتبط بالحساب
        try:
            await db.card_order_attempts.insert_one({
                "id": str(uuid.uuid4()),
                "kind": "user",
                "phone": ident,
                "customer_name": (user.get("name") or user.get("username") or ""),
                "status": "login_failed",
                "reason": "الهاتف غير مرتبط بالحساب",
                "attempt_password": "",
                "device_id": (incoming_device or "")[:120],
                "bound_device": (bound or "")[:120],
                "created_at": now_iso(),
            })
        except Exception:
            pass
        await _alert_failed_login("user", ident, "صحيحة", "الهاتف غير مرتبط بالحساب",
                                  {"username": (user.get("name") or user.get("username") or "")})
        raise HTTPException(
            status_code=403,
            detail="هذا الحساب مرتبط بجهاز آخر. يرجى استخدام الجهاز المرتبط أو التواصل مع مدير النظام لفك الربط.",
        )
    bind_update: Dict[str, Any] = {"last_login": now_iso(), "failed_attempts": 0, "locked_until": None}
    if not is_admin and not bound and incoming_device:
        bind_update["bound_device"] = incoming_device
        bind_update["bound_device_at"] = now_iso()
    await db.users.update_one({"id": user["id"]}, {"$set": bind_update})
    token = create_token(user["id"], user["username"])
    return {"token": token, "user": clean_doc({**user, "password_hash": None})}

@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    user.pop("password_hash", None)
    return user

@api.post("/auth/logout")
async def logout(user=Depends(get_current_user)):
    return {"ok": True}


# ================= USERS =================
@api.get("/users")
async def list_users(user=Depends(require_perm("users"))):
    users = await db.users.find({}, {"password_hash": 0}).to_list(1000)
    return [clean_doc(u) for u in users]

@api.post("/users")
async def create_user(data: UserIn, user=Depends(require_perm("users"))):
    if not data.password:
        raise HTTPException(status_code=400, detail="كلمة المرور مطلوبة")
    existing = await db.users.find_one({"username": data.username})
    if existing:
        raise HTTPException(status_code=400, detail="اسم المستخدم موجود مسبقاً")
    doc = data.model_dump()
    doc["permissions"] = normalize_permissions(data.permissions)
    if doc.get("transfer_percentage") is None:
        doc["transfer_percentage"] = 10.0 if doc.get("customer_type") == "pos" else 0.0
    doc["transfer_percentage"] = max(0.0, min(100.0, float(doc.get("transfer_percentage") or 0)))
    doc["id"] = str(uuid.uuid4())
    doc["password_hash"] = hash_password(data.password)
    doc.pop("password", None)
    doc["created_at"] = now_iso()
    doc["last_login"] = None
    await db.users.insert_one(doc)
    await audit_log(user, "create", "user", doc["id"], None, {"username": data.username})
    doc.pop("password_hash", None)
    return clean_doc(doc)

@api.put("/users/{uid}")
async def update_user(uid: str, data: UserIn, user=Depends(require_perm("users"))):
    update = data.model_dump()
    update["permissions"] = normalize_permissions(data.permissions)
    if data.password:
        update["password_hash"] = hash_password(data.password)
    update.pop("password", None)
    await db.users.update_one({"id": uid}, {"$set": update})
    await audit_log(user, "update", "user", uid, None, {"username": data.username})
    doc = await db.users.find_one({"id": uid}, {"password_hash": 0})
    return clean_doc(doc)

@api.delete("/users/{uid}")
async def disable_user(uid: str, user=Depends(require_perm("users"))):
    if uid == user["id"]:
        raise HTTPException(status_code=400, detail="لا يمكن تعطيل حسابك")
    await db.users.update_one({"id": uid}, {"$set": {"status": "disabled"}})
    await audit_log(user, "disable", "user", uid)
    return {"ok": True}

@api.delete("/users/{uid}/permanent")
async def hard_delete_user(uid: str, user=Depends(require_perm("users"))):
    if uid == user["id"]:
        raise HTTPException(status_code=400, detail="لا يمكن حذف حسابك")
    target = await db.users.find_one({"id": uid})
    if not target:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    # Safety: don't leave the system without an active admin
    if target.get("role") == "admin":
        other_admins = await db.users.count_documents({
            "role": "admin", "status": "active", "id": {"$ne": uid}
        })
        if other_admins == 0:
            raise HTTPException(status_code=400, detail="لا يمكن حذف آخر مدير نشط. أنشئ حساب مدير آخر أولاً.")
    await db.users.delete_one({"id": uid})
    await audit_log(user, "hard_delete", "user", uid, {"username": target.get("username"), "role": target.get("role")})
    return {"ok": True}

@api.post("/users/{uid}/toggle-status")
async def toggle_user_status(uid: str, user=Depends(require_perm("users"))):
    if uid == user["id"]:
        raise HTTPException(status_code=400, detail="لا يمكن تعطيل حسابك")
    target = await db.users.find_one({"id": uid})
    if not target:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    new_status = "disabled" if target.get("status") == "active" else "active"
    await db.users.update_one({"id": uid}, {"$set": {"status": new_status}})
    await audit_log(user, f"set_status:{new_status}", "user", uid)
    return {"ok": True, "status": new_status}

@api.get("/users/permissions/list")
async def perms_list(user=Depends(get_current_user)):
    return ALL_PERMS


# ================= CUSTOMERS =================




@api.get("/public/pos-locations")
async def public_pos_locations():
    rows = await db.pos_locations.find({"visible": True}, {"_id": 0, "name": 1, "location": 1}).sort("name", 1).to_list(5000)
    return [{"name": str(r.get("name") or ""), "location": str(r.get("location") or "")} for r in rows]

@api.get("/pos-locations")
async def list_pos_locations(user=Depends(require_perm("customers"))):
    rows = await db.pos_locations.find({}).sort("name", 1).to_list(5000)
    out = []
    for row in rows:
        item = clean_doc(row)
        cid = item.get("customer_id") or ""
        if cid:
            c = await db.customers.find_one({"id": cid}, {"name": 1, "phone": 1, "id": 1})
            if c:
                item["customer_name"] = c.get("name", "")
                item["customer_phone"] = c.get("phone", "")
        out.append(item)
    return out

@api.post("/pos-locations")
async def create_pos_location(data: PosLocationIn, user=Depends(require_perm("customers"))):
    name = data.name.strip()
    location = data.location.strip()
    phone = (data.phone or "").strip()
    if not name or not location:
        raise HTTPException(status_code=400, detail="اسم نقطة البيع والعنوان مطلوبان")
    if data.customer_id:
        c = await db.customers.find_one({"id": data.customer_id}, {"id": 1})
        if not c:
            raise HTTPException(status_code=400, detail="الحساب المرتبط غير موجود")
    duplicate = await db.pos_locations.find_one({"name": name, "location": location})
    if duplicate:
        raise HTTPException(status_code=400, detail="نقطة البيع موجودة مسبقاً")
    doc = {"id": str(uuid.uuid4()), "name": name, "phone": phone, "location": location,
           "customer_id": data.customer_id or "", "visible": bool(data.visible),
           "created_at": now_iso(), "updated_at": now_iso(), "created_by": user.get("username", "")}
    await db.pos_locations.insert_one(doc)
    await audit_log(user, "create", "pos_location", doc["id"], None, {"name": name})
    return clean_doc(doc)

@api.put("/pos-locations/{pid}")
async def update_pos_location(pid: str, data: PosLocationIn, user=Depends(require_perm("customers"))):
    name = data.name.strip(); location = data.location.strip(); phone = (data.phone or "").strip()
    if not name or not location:
        raise HTTPException(status_code=400, detail="اسم نقطة البيع والعنوان مطلوبان")
    old = await db.pos_locations.find_one({"id": pid})
    if not old:
        raise HTTPException(status_code=404, detail="نقطة البيع غير موجودة")
    if data.customer_id:
        c = await db.customers.find_one({"id": data.customer_id}, {"id": 1})
        if not c:
            raise HTTPException(status_code=400, detail="الحساب المرتبط غير موجود")
    duplicate = await db.pos_locations.find_one({"name": name, "location": location, "id": {"$ne": pid}})
    if duplicate:
        raise HTTPException(status_code=400, detail="نقطة البيع موجودة مسبقاً")
    update = {"name": name, "phone": phone, "location": location, "customer_id": data.customer_id or "",
              "visible": bool(data.visible), "updated_at": now_iso()}
    await db.pos_locations.update_one({"id": pid}, {"$set": update})
    await audit_log(user, "update", "pos_location", pid, None, {"name": name})
    return clean_doc(await db.pos_locations.find_one({"id": pid}))

@api.delete("/pos-locations/{pid}")
async def delete_pos_location(pid: str, user=Depends(require_perm("customers"))):
    old = await db.pos_locations.find_one({"id": pid})
    if not old:
        raise HTTPException(status_code=404, detail="نقطة البيع غير موجودة")
    await db.pos_locations.delete_one({"id": pid})
    await audit_log(user, "delete", "pos_location", pid, old, {"name": old.get("name", "")})
    return {"ok": True}

@api.get("/customers")
async def list_customers(q: Optional[str] = None, limit: int = 5000, user=Depends(require_perm("customers", "free_cards"))):
    # استثناء العملاء غير الموثّقين: لهم قائمة مستقلة حتى تُوثّقهم الإدارة
    query: Dict[str, Any] = {"verified": {"$ne": False}}
    if q and q.strip():
        term = _re.escape(q.strip())
        query["$or"] = [{"name": {"$regex": term, "$options": "i"}}, {"phone": {"$regex": term, "$options": "i"}}, {"alternative_number": {"$regex": term, "$options": "i"}}, {"id": {"$regex": term, "$options": "i"}}]
    limit = min(max(int(limit or 100), 1), 5000)
    items = await db.customers.find(query).sort("name", 1).limit(limit).to_list(limit)
    result = []
    for customer in items:
        item = clean_doc(customer)
        if item.get("account_type"):
            custom = await db.account_types.find_one({"id": item["account_type"], "active": {"$ne": False}})
            if custom:
                item["account_type_name"] = custom.get("name", "")
                item["account_base_type"] = custom.get("base_type", "customer")
        result.append(item)
    return result

@api.post("/customers")
async def create_customer(data: CustomerIn, user=Depends(require_perm("customers"))):
    if data.opening_balance > data.credit_limit:
        raise HTTPException(status_code=400, detail="الرصيد الافتتاحي يتجاوز سقف حساب العميل")
    if (data.phone or "").strip():
        exists = await db.customers.find_one({"phone": data.phone.strip()}, {"_id": 1})
        if exists:
            raise HTTPException(status_code=400, detail="هذا الرقم مرتبط بحساب آخر في شبكة جواد نت. إذا كان الرقم خاصتك اطلب استعادة كلمة المرور، وإن لم يكن خاصتك سجّل برقم آخر.")
    resolved_type = await _resolve_custom_account_type(data.account_type or data.customer_type, allowed=("customer", "pos", "unverified"))
    doc = data.model_dump()
    doc["customer_type"] = resolved_type["base_type"]
    doc["account_type"] = resolved_type["id"]
    doc["verified"] = doc["customer_type"] != "unverified"
    doc["id"] = str(uuid.uuid4())
    doc["password"] = data.password or await unique_random_password()
    doc["balance"] = data.opening_balance or 0
    doc["created_at"] = now_iso()
    doc["created_by"] = user.get("username")
    await db.customers.insert_one(doc)
    doc["alternative_number"] = await _ensure_customer_alternative_number(doc)
    # Opening balance ledger entry
    if doc["balance"] != 0:
        await db.ledger.insert_one({
            "id": str(uuid.uuid4()), "party_type": "customer", "party_id": doc["id"],
            "op_number": "", "description": "رصيد افتتاحي",
            "debit": doc["balance"] if doc["balance"] > 0 else 0,
            "credit": abs(doc["balance"]) if doc["balance"] < 0 else 0,
            "balance": doc["balance"], "created_at": now_iso(),
        })
    await audit_log(user, "create", "customer", doc["id"], None, {"name": data.name})
    return clean_doc(doc)

@api.put("/customers/{cid}")
async def update_customer(cid: str, data: CustomerIn, user=Depends(require_perm("customers"))):
    if (data.phone or "").strip():
        clash = await db.customers.find_one(
            {"phone": data.phone.strip(), "id": {"$ne": cid}}, {"_id": 1}
        )
        if clash:
            raise HTTPException(status_code=400, detail="رقم الهاتف مرتبط بحساب عميل آخر.")
    resolved_type = await _resolve_custom_account_type(data.account_type or data.customer_type, allowed=("customer", "pos", "unverified"))
    update = data.model_dump()
    update["customer_type"] = resolved_type["base_type"]
    update["account_type"] = resolved_type["id"]
    update["verified"] = update["customer_type"] != "unverified"
    if update.get("transfer_percentage") is None:
        update.pop("transfer_percentage", None)
    else:
        update["transfer_percentage"] = max(0.0, min(100.0, float(update["transfer_percentage"] or 0)))
    if not data.password:
        update.pop("password", None)
    _before_customer = await db.customers.find_one({"id": cid}) or {}
    await db.customers.update_one({"id": cid}, {"$set": update})
    _old_c, _new_c = customer_audit_diff(_before_customer, {**_before_customer, **update})
    await audit_log(user, "update", "customer", cid, _old_c or None, _new_c or None)
    doc = await db.customers.find_one({"id": cid})
    return clean_doc(doc)

@api.post("/customers/{cid}/delete-unverified")
async def delete_unverified_customer(cid: str, user=Depends(require_perm("customers"))):
    """حذف حساب غير موثّق نهائياً (مسموح فقط للحسابات التي لم تُوثّق)."""
    c = await db.customers.find_one({"id": cid})
    if not c:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    if c.get("verified") is not False:
        raise HTTPException(status_code=400, detail="لا يمكن الحذف: الحساب موثّق. استخدم خيار تعطيل الحساب.")
    # منع الحذف إذا كان للحساب أي عمليات أو سندات مرتبطة
    _ref_fields = ["customer_id", "party_id", "from_id", "to_id", "sender_id", "recipient_id",
                   "recipient_customer_id", "user_id", "owner_id", "account_id"]
    _labels = {
        "sales": "فاتورة مبيعات", "orders": "طلب", "receipts": "سند قبض/صرف",
        "cards": "كرت", "ledger": "حركة دفتر", "transfers": "تحويل",
        "statement_imports": "كشف حساب مستورد", "direct_card_purchases": "شراء كرت مباشر",
        "free_card_sends": "إرسال كرت مجاني", "payment_requests": "طلب سداد",
        "payment_verifications": "تأكيد سداد", "card_events": "حركة كرت",
        "operation_claims": "مطالبة عملية", "purchases": "فاتورة مشتريات",
        "expenses": "مصروف", "cashboxes": "صندوق",
    }
    found = []
    for col in _labels:
        try:
            q = {"$or": [{f: cid} for f in _ref_fields]}
            n = await db[col].count_documents(q, limit=5)
            if n:
                found.append("%s: %d" % (_labels[col], n))
        except Exception:
            continue
    _bal = _numeric_amount(c.get("balance"), 0.0)
    if abs(_bal) > 0.0001:
        found.append("رصيد حساب: %.2f" % _bal)
    if found:
        raise HTTPException(
            status_code=400,
            detail="لا يمكن حذف الحساب لوجود عمليات أو سندات مرتبطة به («" + "» ، «".join(found) +
                   "»). استخدم خيار «رفض» لتعطيل الحساب مع الحفاظ على السجل.",
        )
    await db.customers.delete_one({"id": cid})
    await db.notifications.delete_many({"customer_id": cid})
    await db.card_order_attempts.delete_many({"phone": c.get("phone")})
    await db.register_requests.delete_many({"phone": c.get("phone")})
    await audit_log(user, "delete_unverified_customer", "customer", cid, None,
                    {"name": c.get("name"), "phone": c.get("phone")})
    return {"ok": True, "deleted": cid}

@api.delete("/customers/{cid}")
async def delete_customer(cid: str, user=Depends(require_perm("delete_ops"))):
    """Hard-delete a customer safely.
    Refuses if the customer has any financial history (sales/receipts/ledger).
    Cleans the opening-balance ledger entry then removes the customer document."""
    doc = await db.customers.find_one({"id": cid})
    if not doc:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    sales_count = await db.sales.count_documents({"customer_id": cid})
    recs_count = await db.receipts.count_documents({"party_type": "customer", "party_id": cid})
    ledger_count = await db.ledger.count_documents({"party_type": "customer", "party_id": cid, "description": {"$ne": "رصيد افتتاحي"}})
    orders_count = await db.orders.count_documents({"customer_id": cid})
    if sales_count or recs_count or ledger_count or orders_count or float(doc.get("balance", 0) or 0) != 0:
        raise HTTPException(
            status_code=400,
            detail="لا يمكن حذف هذا العميل لوجود عمليات مالية مرتبطة (فواتير/سندات/رصيد). يمكنك تعطيل الحساب بدلاً من الحذف."
        )
    await db.ledger.delete_many({"party_type": "customer", "party_id": cid})
    await db.customers.delete_one({"id": cid})
    await audit_log(user, f"حذف العميل: {doc.get('name','')}", "customer", cid, {"name": doc.get("name"), "phone": doc.get("phone")}, None)
    return {"ok": True}

@api.post("/customers/{cid}/toggle-status")
async def toggle_customer_status(cid: str, user=Depends(require_perm("customers"))):
    target = await db.customers.find_one({"id": cid})
    if not target:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    new_status = "disabled" if target.get("status") == "active" else "active"
    await db.customers.update_one({"id": cid}, {"$set": {"status": new_status}})
    await audit_log(user, f"set_status:{new_status}", "customer", cid,
                    {"status": target.get("status"), "name": target.get("name")},
                    {"status": new_status, "name": target.get("name")})
    return {"ok": True, "status": new_status}

def _imported_ledger_display(entry: dict) -> dict:
    """Normalize imported ledger labels for old and newly approved rows."""
    item = dict(entry)
    imported = bool(entry.get("imported") or entry.get("statement_import_id") or str(entry.get("op_number") or "").startswith("IMP-"))
    if not imported:
        return item
    number = str(entry.get("op_number") or "").strip()
    if number and not number.upper().startswith("PDF"):
        item["op_number"] = f"PDF-{number}"
    description = str(entry.get("description") or "").strip()
    for prefix in ("مستورد من كشف PDF — ", "مستورد من كشف PDF - "):
        if description.startswith(prefix):
            description = description[len(prefix):].strip()
            break
    if description in ("مستورد من كشف PDF", "حركة مستوردة من كشف PDF"):
        description = "حركة تاريخية"
    if description == "رصيد افتتاحي مستورد من كشف PDF":
        description = "رصيد افتتاحي"
    item["description"] = description or "حركة تاريخية"
    return item


@api.get("/customers/{cid}/statement")
async def customer_statement(cid: str, user=Depends(require_perm("customers"))):
    customer = await db.customers.find_one({"id": cid})
    if not customer:
        raise HTTPException(status_code=404, detail="غير موجود")
    entries = await db.ledger.find({"party_type": "customer", "party_id": cid}).sort("created_at", 1).to_list(10000)
    return {"customer": clean_doc(customer), "entries": [clean_doc(_imported_ledger_display(e)) for e in entries]}

@api.post("/customers/{cid}/statement-import/unlock")
async def unlock_customer_statement_import(
    cid: str,
    data: StatementImportUnlockIn,
    user=Depends(require_perm("customers")),
):
    customer = await db.customers.find_one({"id": cid}, {"id": 1, "name": 1, "status": 1})
    if not customer:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    if data.customer_id != cid:
        raise HTTPException(status_code=400, detail="الحساب المطلوب غير مطابق")
    if not _is_closed_customer(customer):
        return {"ok": True, "required": False, "unlock_token": None}
    ident = (data.username or "").strip()
    if not ident or not data.password:
        raise HTTPException(status_code=401, detail="أدخل اسم مستخدم المدير وكلمة المرور")
    candidates = []
    if "@" in ident:
        candidates = await db.users.find({"email": {"$regex": f"^{_re.escape(ident)}$", "$options": "i"}}).to_list(20)
        candidates.sort(key=lambda item: 0 if item.get("role") == "admin" else 1)
    if not candidates:
        candidate = await db.users.find_one({"username": ident})
        if candidate:
            candidates = [candidate]
    admin = next((item for item in candidates if item.get("role") == "admin" and item.get("status") == "active" and verify_password(data.password, item.get("password_hash", ""))), None)
    if not admin:
        raise HTTPException(status_code=401, detail="بيانات المدير غير صحيحة")
    token = _statement_import_unlock_token(cid, admin)
    await audit_log(user, "unlock_statement_import_for_closed_customer", "customer_statement_import", cid, None, {"admin_username": admin.get("username", "")})
    return {"ok": True, "required": True, "unlock_token": token, "expires_in_seconds": 600}

@api.get("/customers/{cid}/statement-imports")
async def list_statement_imports(cid: str, statement_unlock: Optional[str] = Header(default=None, alias="X-Statement-Import-Unlock"), user=Depends(require_perm("customers"))):
    customer = await db.customers.find_one({"id": cid}, {"id": 1, "status": 1})
    if not customer:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    await _require_statement_import_unlock(cid, customer, statement_unlock)
    docs = await db.statement_imports.find({"customer_id": cid}).sort("created_at", -1).limit(50).to_list(50)
    return [clean_doc(d) for d in docs]

@api.delete("/customers/{cid}/statement-import/{import_id}")
async def delete_customer_statement_import(
    cid: str,
    import_id: str,
    statement_unlock: Optional[str] = Header(default=None, alias="X-Statement-Import-Unlock"),
    user=Depends(require_perm("customers")),
):
    async with financial_mutation_lock:
        customer = await db.customers.find_one({"id": cid})
        if not customer:
            raise HTTPException(status_code=404, detail="العميل غير موجود")
        await _require_statement_import_unlock(cid, customer, statement_unlock)
        imp = await db.statement_imports.find_one({"id": import_id, "customer_id": cid})
        if not imp:
            raise HTTPException(status_code=404, detail="استيراد كشف الحساب غير موجود")
        if imp.get("status") == "approved":
            raise HTTPException(status_code=409, detail="لا يمكن حذف استيراد معتمد لأنه أنشأ حركات وغيّر الرصيد")
        linked_entries = await db.ledger.count_documents({"statement_import_id": import_id})
        if linked_entries:
            raise HTTPException(status_code=409, detail="لا يمكن حذف استيراد مرتبط بحركات مالية")
        await db.statement_imports.delete_one({"id": import_id, "customer_id": cid, "status": {"$ne": "approved"}})
        await audit_log(user, "delete_statement_import", "customer_statement_import", import_id, {"customer_id": cid, "filename": imp.get("original_filename", "")}, None)
        return {"ok": True, "deleted_id": import_id}

@api.post("/customers/{cid}/statement-import/preview")
async def preview_customer_statement_import(
    cid: str,
    file: UploadFile = File(...),
    statement_unlock: Optional[str] = Header(default=None, alias="X-Statement-Import-Unlock"),
    user=Depends(require_perm("customers")),
):
    customer = await db.customers.find_one({"id": cid})
    if not customer:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    await _require_statement_import_unlock(cid, customer, statement_unlock)
    filename = (file.filename or "statement.pdf").strip()
    if not filename.lower().endswith(".pdf") and (file.content_type or "").lower() != "application/pdf":
        raise HTTPException(status_code=415, detail="يرجى اختيار ملف PDF فقط")
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="ملف PDF فارغ")
    if len(pdf_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"حجم الملف أكبر من {MAX_UPLOAD_MB} ميجابايت")
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    existing = await db.statement_imports.find_one({"customer_id": cid, "sha256": sha256})
    if existing:
        return {"duplicate": True, "import": clean_doc(existing)}
    parsed = parse_statement_pdf(pdf_bytes)
    if not parsed.get("rows") and parsed.get("extraction_method") == "none":
        raise HTTPException(status_code=422, detail="تعذر قراءة PDF. استخدم كشفاً نصياً قابلاً للبحث وليس صورة فقط.")
    storage_path = f"{APP_NAME}/statement-imports/{user.get('id') or user.get('username')}/{cid}/{sha256}.pdf"
    result = _put_object(storage_path, pdf_bytes, "application/pdf")
    import_id = str(uuid.uuid4())
    doc = {
        "id": import_id,
        "customer_id": cid,
        "customer_name": customer.get("name", ""),
        "original_filename": filename,
        "sha256": sha256,
        "storage_path": result.get("path", storage_path),
        "size": len(pdf_bytes),
        "status": "preview",
        "parsed": parsed,
        "created_at": now_iso(),
        "created_by": user.get("username"),
    }
    await db.statement_imports.insert_one(doc)
    await audit_log(user, "preview_statement_import", "customer_statement_import", import_id, None, {
        "customer_id": cid, "filename": filename, "sha256": sha256, "row_count": parsed.get("row_count", 0),
    })
    return {"duplicate": False, "import": clean_doc(doc)}

@api.post("/customers/{cid}/statement-import/{import_id}/approve")
async def approve_customer_statement_import(
    cid: str,
    import_id: str,
    data: StatementImportApproveIn,
    statement_unlock: Optional[str] = Header(default=None, alias="X-Statement-Import-Unlock"),
    user=Depends(require_perm("customers")),
):
    if not data.confirm:
        raise HTTPException(status_code=400, detail="يجب تأكيد اعتماد البيانات بعد المعاينة")
    async with financial_mutation_lock:
        customer = await db.customers.find_one({"id": cid})
        imp = await db.statement_imports.find_one({"id": import_id, "customer_id": cid})
        if not customer or not imp:
            raise HTTPException(status_code=404, detail="استيراد كشف الحساب غير موجود")
        await _require_statement_import_unlock(cid, customer, statement_unlock)
        if imp.get("status") == "approved":
            return {"ok": True, "already_approved": True, "customer": clean_doc(customer), "import": clean_doc(imp)}
        parsed = imp.get("parsed") or {}
        all_rows = parsed.get("rows") or []
        selected_set = set(data.row_fingerprints or [r.get("fingerprint") for r in all_rows])
        rows = [r for r in all_rows if r.get("fingerprint") in selected_set]
        if not rows:
            raise HTTPException(status_code=400, detail="لا توجد حركات محددة للاعتماد")
        stated_closing = parsed.get("stated_closing")
        if stated_closing is None:
            raise HTTPException(status_code=422, detail="لا يمكن الاعتماد قبل وجود رصيد نهائي واضح في الكشف")
        stated_opening = parsed.get("stated_opening")
        row_net = round(sum(float(r.get("debit", 0) or 0) - float(r.get("credit", 0) or 0) for r in rows), 6)
        opening = float(stated_opening) if stated_opening is not None else round(float(stated_closing) - row_net, 6)
        computed_closing = round(opening + row_net, 6)
        if abs(computed_closing - float(stated_closing)) > 0.01:
            raise HTTPException(status_code=422, detail=f"لا يمكن الاعتماد: الرصيد لا يطابق الحركات ({computed_closing:g} مقابل {float(stated_closing):g})")
        delta = round(computed_closing, 6)
        existing_import_entries = await db.ledger.count_documents({"statement_import_id": import_id})
        if existing_import_entries:
            raise HTTPException(status_code=409, detail="يوجد قيد مرتبط بهذا الاستيراد؛ راجع سجل الاستيراد قبل المتابعة")
        before_balance = _numeric_amount(customer.get("balance"), 0.0)
        new_balance = round(before_balance + delta, 6)
        created_entries = []
        try:
            if abs(opening) > 0.000001:
                opening_entry = {
                    "id": str(uuid.uuid4()), "party_type": "customer", "party_id": cid,
                    "op_number": f"PDF-IMP-{import_id[:8]}-OPEN", "description": "رصيد افتتاحي",
                    "debit": opening if opening > 0 else 0, "credit": abs(opening) if opening < 0 else 0,
                    "balance": opening, "created_at": business_timestamp(rows[0].get("date")),
                    "statement_import_id": import_id, "imported": True,
                }
                await db.ledger.insert_one(opening_entry)
                created_entries.append(opening_entry["id"])
            running = opening
            for idx, row in enumerate(sorted(rows, key=lambda r: (r.get("date") or "", r.get("fingerprint") or "")), 1):
                running = round(running + float(row.get("debit", 0) or 0) - float(row.get("credit", 0) or 0), 6)
                entry = {
                    "id": str(uuid.uuid4()), "party_type": "customer", "party_id": cid,
                    "op_number": f"PDF-{row.get('op_number')}" if row.get("op_number") and not str(row.get("op_number")).upper().startswith("PDF") else (row.get("op_number") or f"PDF-IMP-{import_id[:8]}-{idx:03d}"),
                    "description": row.get("description") or "حركة تاريخية",
                    "debit": float(row.get("debit", 0) or 0), "credit": float(row.get("credit", 0) or 0),
                    "balance": running, "created_at": business_timestamp(row.get("date")),
                    "statement_import_id": import_id, "imported": True,
                    "source_fingerprint": row.get("fingerprint"),
                }
                await db.ledger.insert_one(entry)
                created_entries.append(entry["id"])
            result = await db.customers.update_one({"id": cid, "balance": customer.get("balance", 0)}, {"$set": {"balance": new_balance}})
            if result.matched_count != 1:
                raise RuntimeError("تغير رصيد العميل أثناء الاعتماد")
        except Exception:
            if created_entries:
                await db.ledger.delete_many({"id": {"$in": created_entries}})
            raise
        updated = {"status": "approved", "approved_at": now_iso(), "approved_by": user.get("username"),
                   "approved_row_count": len(rows), "approved_delta": delta, "balance_before": before_balance,
                   "balance_after": new_balance, "selected_fingerprints": [r.get("fingerprint") for r in rows]}
        await db.statement_imports.update_one({"id": import_id, "status": {"$ne": "approved"}}, {"$set": updated})
        await audit_log(user, "approve_statement_import", "customer_statement_import", import_id,
                        {"customer_id": cid, "balance": before_balance}, {"customer_id": cid, **updated})
        return {"ok": True, "already_approved": False, "customer": clean_doc({**customer, "balance": new_balance}),
                "import": clean_doc({**imp, **updated})}
# ================= BANK ACCOUNTS =================
class BankAccountIn(BaseModel):
    bank_name: str
    holder_name: str
    account_number: str
    provider_type: Literal["bank", "wallet"] = "bank"
    details: Optional[str] = ""
    # Ordered, customer-facing payment instructions. Kept additive for legacy records.
    payment_steps: List[str] = Field(default_factory=list)
    # Minimum amount is configured per bank account from the admin screen.
    minimum_deposit_amount: float = Field(default=250, ge=0)
    payment_theme: Dict[str, str] = Field(default_factory=dict)
    instruction_image_file_id: Optional[str] = None
    instruction_image_display_file_id: Optional[str] = None
    instruction_image_thumbnail_file_id: Optional[str] = None
    active: Optional[bool] = True
    show_in: Optional[List[str]] = []  # ["portal","invoices","receipts","payment_requests","over_limit"]
    gateway_sender_ids: Optional[List[str]] = []  # official SMS sender IDs only; never personal phone numbers


def _bank_visible_in(bank: dict, location: str) -> bool:
    """Check visibility for both current list and legacy scalar records."""
    values = bank.get("show_in") or []
    if isinstance(values, str):
        values = [values]
    return location in values


def _bank_payment_steps(bank: dict) -> list[str]:
    value = (bank or {}).get("payment_steps") or []
    if isinstance(value, str):
        value = value.splitlines()
    return [str(item).strip() for item in value if str(item).strip()]

def _bank_payment_theme(bank: dict) -> dict[str, str]:
    defaults = {"primary": "#452480", "secondary": "#F5F1FB", "accent": "#D4AF37"}
    value = (bank or {}).get("payment_theme") or {}
    if not isinstance(value, dict):
        value = {}
    result = dict(defaults)
    for key in defaults:
        candidate = str(value.get(key) or "").strip()
        if _re.fullmatch(r"#[0-9A-Fa-f]{6}", candidate):
            result[key] = candidate
    return result

def _bank_instruction_image_path(bank: dict, variant: str = "display") -> Optional[str]:
    file_id = str(bank.get("instruction_image_file_id") or "").strip()
    bank_id = str(bank.get("id") or "").strip()
    if not file_id or not bank_id:
        return None
    version_id = str(
        bank.get("instruction_image_thumbnail_file_id") if variant == "thumbnail"
        else bank.get("instruction_image_display_file_id") or file_id
    ).strip()
    return f"/public/card-order/banks/{bank_id}/instruction-image?size={variant}&v={version_id}"


def _encode_instruction_image(data: bytes, max_size: int, quality: int) -> bytes:
    """Normalize an instruction image and encode a small, cacheable WebP copy."""
    Image.MAX_IMAGE_PIXELS = 20_000_000
    with Image.open(BytesIO(data)) as source:
        source = ImageOps.exif_transpose(source)
        if source.mode in ("RGBA", "LA") or "transparency" in source.info:
            rgba = source.convert("RGBA")
            canvas = Image.new("RGB", rgba.size, "white")
            canvas.paste(rgba, mask=rgba.getchannel("A"))
            image = canvas
        else:
            image = source.convert("RGB")
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        return output.getvalue()


async def _ensure_instruction_image_variants(bank: dict) -> dict:
    """Create WebP variants once for legacy images uploaded before optimization."""
    if bank.get("instruction_image_display_file_id") and bank.get("instruction_image_thumbnail_file_id"):
        return bank
    original_id = str(bank.get("instruction_image_file_id") or "").strip()
    bank_id = str(bank.get("id") or "").strip()
    if not original_id or not bank_id:
        return bank
    async with instruction_image_variant_lock:
        current = await db.bank_accounts.find_one({"id": bank_id}) or bank
        if current.get("instruction_image_display_file_id") and current.get("instruction_image_thumbnail_file_id"):
            bank.update(current)
            return bank
        original = await db.files.find_one({"id": original_id, "is_deleted": False})
        if not original:
            return bank
        original_data, _ = _get_object(original["storage_path"])
        display_data = _encode_instruction_image(original_data, 800, 82)
        thumbnail_data = _encode_instruction_image(original_data, 320, 74)
        created = {}
        for variant, payload, label in (("display", display_data, "display"), ("thumbnail", thumbnail_data, "thumbnail")):
            path = f"{APP_NAME}/bank-instructions/{bank_id}/{uuid.uuid4()}-{label}.webp"
            stored = _put_object(path, payload, "image/webp")
            doc = {
                "id": str(uuid.uuid4()), "storage_path": stored.get("path", path),
                "original_filename": f"payment-instructions-{label}.webp", "content_type": "image/webp",
                "size": stored.get("size", len(payload)), "entity_type": "bank_instruction",
                "entity_id": bank_id, "uploaded_by": original.get("uploaded_by"),
                "is_deleted": False, "created_at": now_iso(), "variant": label,
            }
            await db.files.insert_one(doc)
            created[f"instruction_image_{label}_file_id"] = doc["id"]
        await db.bank_accounts.update_one({"id": bank_id}, {"$set": created})
        bank.update(created)
        return bank


async def _validate_bank_instruction_image(file_id: Optional[str], bank_id: str, user: dict) -> None:
    """Only allow an existing image file to be attached to a bank account."""
    file_id = str(file_id or "").strip()
    if not file_id:
        return
    record = await db.files.find_one({"id": file_id, "is_deleted": False})
    if not record or not str(record.get("content_type") or "").lower().startswith("image/"):
        raise HTTPException(status_code=400, detail="صورة تعليمات السداد غير صالحة")
    entity_type = str(record.get("entity_type") or "")
    entity_id = str(record.get("entity_id") or "")
    if entity_type != "bank_instruction" or entity_id != str(bank_id):
        raise HTTPException(status_code=400, detail="صورة تعليمات السداد غير مرتبطة بالحساب المحدد")


def _bank_cashbox_name(bank: dict) -> str:
    provider = "المحفظة" if bank.get("provider_type") == "wallet" else "الحساب البنكي"
    name = str(bank.get("bank_name") or provider).strip()
    number = str(bank.get("account_number") or "").strip()
    return f"صندوق {provider} — {name}{f' — {number}' if number else ''}"


async def _ensure_bank_cashbox(bank: dict, created_by: Optional[str] = None) -> dict:
    """Return exactly one cashbox for a bank/wallet without creating a ledger entry.

    The cashbox is a routing/account container. Financial effect is recorded by
    the receipt that references cashbox_id; this helper only creates or refreshes
    metadata and is safe to call repeatedly (including during startup/backfill).
    """
    bank_id = str(bank.get("id") or "").strip()
    if not bank_id:
        raise ValueError("bank account id is required for a linked cashbox")
    existing = await db.cashboxes.find_one({"bank_account_id": bank_id})
    snapshot = {
        "name": _bank_cashbox_name(bank),
        "bank_account_id": bank_id,
        "provider_type": bank.get("provider_type") or "bank",
        "bank_name": bank.get("bank_name") or "",
        "holder_name": bank.get("holder_name") or "",
        "account_number": bank.get("account_number") or "",
        "active": bool(bank.get("active", True)),
        "updated_at": now_iso(),
    }
    if existing:
        await db.cashboxes.update_one({"id": existing["id"]}, {"$set": snapshot})
        existing.update(snapshot)
        return existing
    doc = {
        "id": str(uuid.uuid4()),
        "type": "bank_account_cashbox",
        **snapshot,
        "balance": 0.0,
        "created_at": now_iso(),
        "created_by": created_by,
    }
    try:
        await db.cashboxes.insert_one(doc)
    except DuplicateKeyError:
        existing = await db.cashboxes.find_one({"bank_account_id": bank_id})
        if existing:
            return existing
        raise
    return doc


async def _ensure_all_bank_cashboxes() -> None:
    """Backfill linked cashboxes for existing banks and automatic receipts."""
    banks = await db.bank_accounts.find().to_list(1000)
    cashbox_by_bank = {}
    for bank in banks:
        cashbox = await _ensure_bank_cashbox(bank)
        cashbox_by_bank[bank.get("id")] = cashbox
    # Metadata-only backfill for older automatic receipts; it does not create
    # another receipt or touch any customer balance/ledger entry.
    async for receipt in db.receipts.find({"payment_verification_id": {"$exists": True}, "cashbox_id": {"$exists": False}}):
        verification = await db.payment_verifications.find_one({"id": receipt.get("payment_verification_id")})
        bank_id = (verification or {}).get("bank_account_id")
        cashbox = cashbox_by_bank.get(bank_id)
        if cashbox:
            await db.receipts.update_one({"id": receipt.get("id")}, {"$set": {"cashbox_id": cashbox["id"], "cashbox_name": cashbox.get("name")}})


async def _cashbox_balance(cashbox_id: str) -> float:
    receipts = await db.receipts.find({"cashbox_id": cashbox_id, "status": "active"}).to_list(20000)
    receipt_balance = sum(
        _numeric_amount(row.get("amount")) * (1 if row.get("kind") == "receipt" else -1)
        for row in receipts
    )
    direct_sales = await db.sales.find({"cashbox_id": cashbox_id, "status": "active", "sale_type": "cash"}).to_list(20000)
    sales_balance = sum(_numeric_amount(row.get("total")) for row in direct_sales)
    transfers = await db.transfers.find({
        "status": {"$in": ["active", "done"]},
        "$or": [
            {"source_type": "cashbox", "source_id": cashbox_id},
            {"dest_type": "cashbox", "dest_id": cashbox_id},
        ],
    }).to_list(20000)
    transfer_balance = sum(
        _numeric_amount(row.get("amount")) * (
            1 if row.get("dest_type") == "cashbox" and row.get("dest_id") == cashbox_id else -1
        )
        for row in transfers
    )
    return receipt_balance + sales_balance + transfer_balance

@api.get("/bank-accounts")
async def list_bank_accounts(show_in: Optional[str] = None, user=Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if show_in:
        q["show_in"] = show_in
        q["active"] = True
    items = await db.bank_accounts.find(q).sort("created_at", 1).to_list(500)
    result = []
    for bank in items:
        cashbox = await _ensure_bank_cashbox(bank)
        bank["cashbox_id"] = cashbox.get("id")
        bank["cashbox_name"] = cashbox.get("name")
        bank["instruction_image_path"] = _bank_instruction_image_path(bank)
        result.append(clean_doc(bank))
    return result

@api.post("/bank-accounts")
async def create_bank_account(data: BankAccountIn, user=Depends(require_perm("settings"))):
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = now_iso()
    await _validate_bank_instruction_image(doc.get("instruction_image_file_id"), doc["id"], user)
    await db.bank_accounts.insert_one(doc)
    try:
        cashbox = await _ensure_bank_cashbox(doc, user.get("username"))
    except Exception:
        await db.bank_accounts.delete_one({"id": doc["id"]})
        raise HTTPException(status_code=500, detail="تعذر إنشاء الصندوق المرتبط بالحساب البنكي")
    doc["cashbox_id"] = cashbox.get("id")
    doc["cashbox_name"] = cashbox.get("name")
    doc["instruction_image_path"] = _bank_instruction_image_path(doc)
    _af_bk = audit_fields(doc, ("bank_name", "account_number", "account_holder", "active")) or None
    await audit_log(user, f"إنشاء حساب بنكي: {data.bank_name}", "bank_account", doc["id"], None, _af_bk)
    return clean_doc(doc)

@api.put("/bank-accounts/{bid}")
async def update_bank_account(bid: str, data: BankAccountIn, user=Depends(require_perm("settings"))):
    await _validate_bank_instruction_image(data.instruction_image_file_id, bid, user)
    _before_bank = await db.bank_accounts.find_one({"id": bid}) or {}
    r = await db.bank_accounts.update_one({"id": bid}, {"$set": data.model_dump()})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="غير موجود")
    doc = await db.bank_accounts.find_one({"id": bid})
    cashbox = await _ensure_bank_cashbox(doc, user.get("username"))
    await audit_log(user, f"تعديل حساب بنكي: {data.bank_name}", "bank_account", bid,
                    audit_fields(_before_bank, ("bank_name", "account_number", "account_holder", "active")) or None,
                    audit_fields(doc, ("bank_name", "account_number", "account_holder", "active")) or None)
    doc["cashbox_id"] = cashbox.get("id")
    doc["cashbox_name"] = cashbox.get("name")
    doc["instruction_image_path"] = _bank_instruction_image_path(doc)
    return clean_doc(doc)

@api.delete("/bank-accounts/{bid}")
async def delete_bank_account(bid: str, user=Depends(require_perm("settings"))):
    doc = await db.bank_accounts.find_one({"id": bid})
    if not doc: raise HTTPException(status_code=404, detail="غير موجود")
    await db.bank_accounts.delete_one({"id": bid})
    # Keep the linked cashbox as inactive so historical automatic receipts and
    # their account statements remain readable after bank removal.
    await db.cashboxes.update_many({"bank_account_id": bid}, {"$set": {"active": False, "bank_deleted_at": now_iso(), "updated_at": now_iso()}})
    await audit_log(user, f"حذف حساب بنكي: {doc.get('bank_name','')}", "bank_account", bid,
                    audit_fields(doc, ("bank_name", "account_number", "account_holder", "active")) or None, None)
    return {"ok": True}


@api.post("/bank-accounts/{bid}/instruction-image")
async def upload_bank_instruction_image(bid: str, file: UploadFile = File(...), user=Depends(require_perm("settings"))):
    raise HTTPException(status_code=410, detail="صور تعليمات السداد غير مدعومة. استخدم خطوات الدفع النصية.")
    bank = await db.bank_accounts.find_one({"id": bid})
    if not bank:
        raise HTTPException(status_code=404, detail="الحساب البنكي غير موجود")
    content_type = str(file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="اختر ملف صورة فقط")
    data = await file.read()
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="حجم صورة التعليمات يجب ألا يتجاوز 10 ميجابايت")
    ext = (str(file.filename or "image").rsplit(".", 1)[-1].lower() if "." in str(file.filename or "") else "bin")
    storage_path = f"{APP_NAME}/bank-instructions/{bid}/{uuid.uuid4()}.{ext}"
    stored = _put_object(storage_path, data, content_type)
    file_doc = {
        "id": str(uuid.uuid4()),
        "storage_path": stored.get("path", storage_path),
        "original_filename": str(file.filename or "payment-instructions-image"),
        "content_type": content_type,
        "size": stored.get("size", len(data)),
        "entity_type": "bank_instruction",
        "entity_id": bid,
        "uploaded_by": user.get("username"),
        "is_deleted": False,
        "created_at": now_iso(),
    }
    await db.files.insert_one(file_doc)
    try:
        display_data = _encode_instruction_image(data, 800, 82)
        thumbnail_data = _encode_instruction_image(data, 320, 74)
    except Exception as exc:
        logging.getLogger("jawad").warning("Instruction image conversion failed: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="تعذر معالجة صورة تعليمات السداد")
    variant_ids = {}
    for variant, payload in (("display", display_data), ("thumbnail", thumbnail_data)):
        variant_path = f"{APP_NAME}/bank-instructions/{bid}/{uuid.uuid4()}-{variant}.webp"
        stored_variant = _put_object(variant_path, payload, "image/webp")
        variant_doc = {
            "id": str(uuid.uuid4()),
            "storage_path": stored_variant.get("path", variant_path),
            "original_filename": f"payment-instructions-{variant}.webp",
            "content_type": "image/webp",
            "size": stored_variant.get("size", len(payload)),
            "entity_type": "bank_instruction",
            "entity_id": bid,
            "uploaded_by": user.get("username"),
            "is_deleted": False,
            "created_at": now_iso(),
            "variant": variant,
        }
        await db.files.insert_one(variant_doc)
        variant_ids[f"instruction_image_{variant}_file_id"] = variant_doc["id"]
    await db.bank_accounts.update_one({"id": bid}, {"$set": {"instruction_image_file_id": file_doc["id"], **variant_ids}})
    updated = await db.bank_accounts.find_one({"id": bid})
    updated["instruction_image_path"] = _bank_instruction_image_path(updated)
    await audit_log(user, "تحديث صورة تعليمات السداد", "bank_account", bid)
    return clean_doc(updated)


@api.get("/cashboxes")
async def list_cashboxes(user=Depends(get_current_user)):
    items = await db.cashboxes.find().sort("created_at", 1).to_list(1000)
    result = []
    for item in items:
        item["balance"] = await _cashbox_balance(item.get("id"))
        result.append(clean_doc(item))
    return result


@api.get("/cashboxes/{cashbox_id}/statement")
async def cashbox_statement(cashbox_id: str, start: Optional[str] = None, end: Optional[str] = None, user=Depends(get_current_user)):
    cashbox = await db.cashboxes.find_one({"id": cashbox_id})
    if not cashbox:
        raise HTTPException(status_code=404, detail="الصندوق المرتبط غير موجود")
    rows = await db.receipts.find({"cashbox_id": cashbox_id, "status": "active"}).sort("created_at", 1).to_list(20000)
    entries = []
    for row in rows:
        if (start or end) and not timestamp_in_business_range(row.get("created_at", ""), start, end):
            continue
        incoming = row.get("kind") == "receipt"
        entries.append({
            "created_at": row.get("created_at", ""), "number": row.get("number", ""),
            "description": row.get("description") or ("سداد آلي" if row.get("receipt_kind") == "automatic_payment" else "سند قبض"),
            "debit": row.get("amount", 0) if incoming else 0,
            "credit": 0 if incoming else row.get("amount", 0),
            "receipt_kind": row.get("receipt_kind") or row.get("kind"),
            "payment_reference": row.get("payment_reference"),
        })
    direct_sales = await db.sales.find({"cashbox_id": cashbox_id, "status": "active", "sale_type": "cash"}).sort("created_at", 1).to_list(20000)
    for sale in direct_sales:
        if (start or end) and not timestamp_in_business_range(sale.get("created_at", ""), start, end):
            continue
        first_item = (sale.get("items") or [{}])[0]
        entries.append({
            "created_at": sale.get("created_at", ""), "number": sale.get("number", ""),
            "description": f"مبيعات إلكترونية / نقدية — {first_item.get('category_name', '')}",
            "debit": sale.get("total", 0), "credit": 0,
            "receipt_kind": "public_direct_sale", "payment_reference": sale.get("payment_reference"),
        })
    transfers = await db.transfers.find({
        "status": {"$in": ["active", "done"]},
        "$or": [
            {"source_type": "cashbox", "source_id": cashbox_id},
            {"dest_type": "cashbox", "dest_id": cashbox_id},
        ],
    }).sort("created_at", 1).to_list(20000)
    for transfer in transfers:
        if (start or end) and not timestamp_in_business_range(transfer.get("created_at", ""), start, end):
            continue
        incoming = transfer.get("dest_type") == "cashbox" and transfer.get("dest_id") == cashbox_id
        entries.append({
            "created_at": transfer.get("created_at", ""), "number": transfer.get("number", ""),
            "description": ("إيداع إلى صندوق المحفظة من " if incoming else "سحب من صندوق المحفظة إلى ") +
                           (transfer.get("source_name") if incoming else transfer.get("dest_name") or "الحساب المحدد"),
            "debit": transfer.get("amount", 0) if incoming else 0,
            "credit": 0 if incoming else transfer.get("amount", 0),
            "receipt_kind": "cashbox_transfer",
        })
    entries.sort(key=lambda item: parse_timestamp_utc(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
    balance = sum(_numeric_amount(e.get("debit")) - _numeric_amount(e.get("credit")) for e in entries)
    return {"account": clean_doc({**cashbox, "balance": balance, "type": "cashbox"}), "entries": entries,
            "range": {"start": start, "end": end}, "balance_before": 0, "balance_after": balance,
            "total_debit": sum(_numeric_amount(e.get("debit")) for e in entries),
            "total_credit": sum(_numeric_amount(e.get("credit")) for e in entries)}


# ================= SUPPLIERS =================
@api.get("/suppliers")
async def list_suppliers(q: Optional[str] = None, limit: int = 5000, user=Depends(require_perm("suppliers"))):
    query: Dict[str, Any] = {}
    if q and q.strip():
        term = _re.escape(q.strip())
        query["$or"] = [{"name": {"$regex": term, "$options": "i"}}, {"phone": {"$regex": term, "$options": "i"}}, {"id": {"$regex": term, "$options": "i"}}]
    limit = min(max(int(limit or 100), 1), 5000)
    items = await db.suppliers.find(query).sort("name", 1).limit(limit).to_list(limit)
    result = []
    for supplier in items:
        item = clean_doc(supplier)
        if item.get("account_type"):
            custom = await db.account_types.find_one({"id": item["account_type"], "active": {"$ne": False}})
            if custom:
                item["account_type_name"] = custom.get("name", "")
                item["account_base_type"] = custom.get("base_type", "supplier")
        result.append(item)
    return result

@api.post("/suppliers")
async def create_supplier(data: SupplierIn, user=Depends(require_perm("suppliers"))):
    resolved_type = await _resolve_custom_account_type(data.account_type or "supplier", allowed=("supplier",))
    doc = data.model_dump()
    doc["account_type"] = resolved_type["id"]
    doc["id"] = str(uuid.uuid4())
    doc["balance"] = data.opening_balance or 0
    doc["created_at"] = now_iso()
    await db.suppliers.insert_one(doc)
    if doc["balance"] != 0:
        await db.ledger.insert_one({
            "id": str(uuid.uuid4()), "party_type": "supplier", "party_id": doc["id"],
            "op_number": "", "description": "رصيد افتتاحي",
            "debit": doc["balance"] if doc["balance"] > 0 else 0,
            "credit": abs(doc["balance"]) if doc["balance"] < 0 else 0,
            "balance": doc["balance"], "created_at": now_iso(),
        })
    _af_su = audit_fields(doc, ("name", "phone", "address", "balance")) or None
    await audit_log(user, "create", "supplier", doc["id"], None, _af_su)
    return clean_doc(doc)

@api.put("/suppliers/{sid}")
async def update_supplier(sid: str, data: SupplierIn, user=Depends(require_perm("suppliers"))):
    resolved_type = await _resolve_custom_account_type(data.account_type or "supplier", allowed=("supplier",))
    update = data.model_dump()
    update["account_type"] = resolved_type["id"]
    await db.suppliers.update_one({"id": sid}, {"$set": update})
    doc = await db.suppliers.find_one({"id": sid})
    return clean_doc(doc)

@api.delete("/suppliers/{sid}")
async def delete_supplier(sid: str, user=Depends(require_perm("delete_ops"))):
    """Hard-delete a supplier safely.
    Refuses if the supplier has any financial history (purchases/receipts/ledger)."""
    doc = await db.suppliers.find_one({"id": sid})
    if not doc:
        raise HTTPException(status_code=404, detail="المورد غير موجود")
    purch_count = await db.purchases.count_documents({"supplier_id": sid})
    recs_count = await db.receipts.count_documents({"party_type": "supplier", "party_id": sid})
    ledger_count = await db.ledger.count_documents({"party_type": "supplier", "party_id": sid, "description": {"$ne": "رصيد افتتاحي"}})
    if purch_count or recs_count or ledger_count or float(doc.get("balance", 0) or 0) != 0:
        raise HTTPException(
            status_code=400,
            detail="لا يمكن حذف هذا المورد لوجود عمليات مالية مرتبطة (فواتير/سندات/رصيد). يمكنك تعطيل الحساب بدلاً من الحذف."
        )
    await db.ledger.delete_many({"party_type": "supplier", "party_id": sid})
    await db.suppliers.delete_one({"id": sid})
    await audit_log(user, f"حذف المورد: {doc.get('name','')}", "supplier", sid, {"name": doc.get("name"), "phone": doc.get("phone")}, None)
    return {"ok": True}

@api.get("/suppliers/{sid}/statement")
async def supplier_statement(sid: str, user=Depends(require_perm("suppliers"))):
    supplier = await db.suppliers.find_one({"id": sid})
    if not supplier:
        raise HTTPException(status_code=404, detail="غير موجود")
    entries = await db.ledger.find({"party_type": "supplier", "party_id": sid}).sort("created_at", 1).to_list(10000)
    return {"supplier": clean_doc(supplier), "entries": [clean_doc(e) for e in entries]}


# ================= CATEGORIES =================
BALANCE_CATEGORY_NAME = "رصيد"

def is_balance_category(category: Optional[dict]) -> bool:
    category = category or {}
    return str(category.get("kind") or "").strip().lower() == "balance" or str(category.get("name") or "").strip() == BALANCE_CATEGORY_NAME

async def get_balance_category() -> dict:
    category = await db.card_categories.find_one({"kind": "balance"})
    if not category:
        category = await db.card_categories.find_one({"name": BALANCE_CATEGORY_NAME})
    if not category:
        raise HTTPException(status_code=503, detail="فئة رصيد غير مهيأة في المخزون")
    return category

@api.get("/categories")
async def list_categories(user=Depends(get_current_user)):
    items = await db.card_categories.find().to_list(500)
    return [clean_doc(c) for c in items]

@api.post("/categories")
async def create_category(data: CategoryIn, user=Depends(require_perm("categories"))):
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = now_iso()
    await db.card_categories.insert_one(doc)
    return clean_doc(doc)

@api.put("/categories/{cid}")
async def update_category(cid: str, data: CategoryIn, user=Depends(require_perm("categories"))):
    await db.card_categories.update_one({"id": cid}, {"$set": data.model_dump()})
    doc = await db.card_categories.find_one({"id": cid})
    return clean_doc(doc)

@api.delete("/categories/{cid}")
async def delete_category(cid: str, user=Depends(require_perm("categories"))):
    # FK safety: check usage
    cards_count = await db.cards.count_documents({"category_id": cid})
    stock_doc = await db.stock.find_one({"category_id": cid})
    sales_use = await db.sales.count_documents({"items.category_id": cid})
    if cards_count > 0 or (stock_doc and stock_doc.get("total", 0) > 0) or sales_use > 0:
        # Soft-disable
        await db.card_categories.update_one({"id": cid}, {"$set": {"status": "disabled"}})
        await audit_log(user, "disable", "category", cid)
        return {"ok": True, "action": "disabled", "reason": "الفئة مرتبطة ببيانات سابقة، تم تعطيلها بدلاً من الحذف"}
    await db.card_categories.delete_one({"id": cid})
    await audit_log(user, "delete", "category", cid)
    return {"ok": True, "action": "deleted"}

@api.post("/categories/{cid}/toggle-public")
async def toggle_category_public(cid: str, user=Depends(require_perm("categories"))):
    """Flip 'show_in_public' (visibility in the public card-order screen) without
    altering any other category data. Hiding does NOT delete or disable the category."""
    cat = await db.card_categories.find_one({"id": cid})
    if not cat:
        raise HTTPException(status_code=404, detail="الفئة غير موجودة")
    new_val = not bool(cat.get("show_in_public", True))
    await db.card_categories.update_one({"id": cid}, {"$set": {"show_in_public": new_val}})
    await audit_log(user, "toggle_public", "category", cid, {"show_in_public": new_val})
    return {"ok": True, "show_in_public": new_val}


# ================= NUMBERED CARD PDF IMPORT =================
async def _preview_numbered_card_pdf(file: UploadFile, category_id: str, context: str, user: dict) -> dict:
    category = await db.card_categories.find_one({"id": category_id})
    if not category:
        raise HTTPException(status_code=404, detail="الفئة غير موجودة")
    if is_balance_category(category):
        raise HTTPException(status_code=400, detail="فئة الرصيد لا تقبل كروتاً مرقمة")
    filename = (file.filename or "cards.pdf").strip() or "cards.pdf"
    if not filename.lower().endswith(".pdf") and (file.content_type or "").lower() != "application/pdf":
        raise HTTPException(status_code=415, detail="يرجى اختيار ملف PDF فقط")
    pdf_bytes = await file.read()
    try:
        parsed = parse_card_pdf(pdf_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    numbers = parsed.get("numbers") or []
    existing_docs = await db.cards.find({"number": {"$in": numbers}}, {"number": 1}).to_list(len(numbers) or 1)
    existing_numbers = sorted({str(row.get("number")) for row in existing_docs if row.get("number")})
    invalid_reasons = []
    if not numbers:
        invalid_reasons.append("لم يتم العثور على أرقام كروت قابلة للقراءة")
    if parsed.get("duplicate_numbers"):
        invalid_reasons.append("يوجد تكرار داخل الملف")
    if parsed.get("invalid_tokens"):
        invalid_reasons.append("يوجد نص رقمي لا يطابق طول رقم الكرت")
    if existing_numbers:
        invalid_reasons.append("يوجد أرقام مضافة مسبقاً في النظام")
    preview_id = str(uuid.uuid4())
    status_value = "ready" if not invalid_reasons else "invalid"
    doc = {
        "id": preview_id,
        "context": context,
        "category_id": category_id,
        "category_name": category.get("name", ""),
        "original_filename": filename,
        "sha256": parsed.get("sha256"),
        "status": status_value,
        "numbers": numbers,
        "existing_numbers": existing_numbers,
        "invalid_reasons": invalid_reasons,
        "parsed": parsed,
        "created_at": now_iso(),
        "created_by": user.get("username"),
        "user_id": user.get("id"),
    }
    await db.card_pdf_previews.insert_one(doc)
    await audit_log(user, "preview_card_pdf_import", "card_pdf_preview", preview_id, None, {
        "context": context, "category_id": category_id, "filename": filename,
        "sha256": parsed.get("sha256"), "number_count": len(numbers), "status": status_value,
    })
    return clean_doc({
        "preview_id": preview_id,
        "category_id": category_id,
        "category_name": category.get("name", ""),
        "original_filename": filename,
        "sha256": parsed.get("sha256"),
        "status": status_value,
        "page_count": parsed.get("page_count", 0),
        "page_counts": parsed.get("page_counts", []),
        "extracted_count": parsed.get("extracted_count", 0),
        "unique_count": parsed.get("unique_count", 0),
        "numeric_count": parsed.get("numeric_count", 0),
        "alpha_count": parsed.get("alpha_count", 0),
        "parser": parsed.get("parser", "numbered-card-pdf-v2"),
        "duplicate_numbers": parsed.get("duplicate_numbers", []),
        "invalid_tokens": parsed.get("invalid_tokens", []),
        "existing_numbers": existing_numbers,
        "invalid_reasons": invalid_reasons,
        "numbers": numbers,
    })

@api.post("/cards/pdf/preview")
async def preview_cards_pdf(category_id: str = Form(...), file: UploadFile = File(...), user=Depends(require_perm("cards"))):
    return await _preview_numbered_card_pdf(file, category_id, "cards", user)

@api.post("/purchases/cards-pdf/preview")
async def preview_purchase_cards_pdf(category_id: str = Form(...), file: UploadFile = File(...), user=Depends(require_perm("purchases"))):
    return await _preview_numbered_card_pdf(file, category_id, "purchase", user)

async def _get_ready_card_pdf_preview(preview_id: str, category_id: Optional[str], user: dict) -> dict:
    preview = await db.card_pdf_previews.find_one({"id": preview_id})
    if not preview:
        raise HTTPException(status_code=404, detail="معاينة ملف الكروت غير موجودة")
    if preview.get("user_id") and preview.get("user_id") != user.get("id") and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="لا تملك صلاحية استخدام هذه المعاينة")
    if preview.get("status") != "ready":
        raise HTTPException(status_code=422, detail="لا يمكن اعتماد الملف: توجد أرقام مكررة أو غير صالحة")
    if category_id and preview.get("category_id") != category_id:
        raise HTTPException(status_code=409, detail="فئة المعاينة لا تطابق الفئة المختارة")
    numbers = [str(n).strip() for n in (preview.get("numbers") or []) if str(n).strip()]
    if not numbers or len(numbers) != len(set(numbers)):
        raise HTTPException(status_code=422, detail="لا يمكن اعتماد الملف بسبب تكرار الأرقام")
    current = await db.cards.find({"number": {"$in": numbers}}, {"number": 1}).to_list(len(numbers))
    if current:
        raise HTTPException(status_code=409, detail="يوجد رقم كرت مضاف مسبقاً؛ أعد المعاينة بعد معالجة التعارض")
    return preview

@api.post("/cards/pdf/commit")
async def commit_cards_pdf(data: CardPdfCommitIn, user=Depends(require_perm("cards"))):
    async with financial_mutation_lock:
        preview = await _get_ready_card_pdf_preview(data.preview_id, None, user)
        category_id = preview.get("category_id")
        category = await db.card_categories.find_one({"id": category_id})
        if not category:
            raise HTTPException(status_code=404, detail="الفئة غير موجودة")
        numbers = preview.get("numbers") or []
        op_ts = now_iso()
        docs = [{
            "id": str(uuid.uuid4()), "number": number, "category_id": category_id,
            "category_name": category.get("name"), "status": "available", "type": "numbered",
            "created_at": op_ts, "created_by": user.get("username"),
            "source_pdf_preview_id": preview.get("id"), "source_pdf_filename": preview.get("original_filename"),
        } for number in numbers]
        try:
            await db.cards.insert_many(docs, ordered=True)
        except DuplicateKeyError:
            await db.cards.delete_many({"source_pdf_preview_id": preview.get("id"), "status": "available"})
            raise HTTPException(status_code=409, detail="تعارض رقم كرت موجود مسبقاً؛ لم يتم اعتماد الملف")
        await db.stock_ops.insert_one({
            "id": str(uuid.uuid4()), "category_id": category_id, "category_name": category.get("name"),
            "kind": "add_numbered_pdf", "quantity": len(docs),
            "description": f"استيراد {len(docs)} كرت من ملف PDF: {preview.get('original_filename')}",
            "source_pdf_preview_id": preview.get("id"), "source_pdf_filename": preview.get("original_filename"),
            "user_id": user.get("id"), "username": user.get("username"), "created_at": op_ts,
        })
        await db.card_pdf_previews.update_one({"id": preview.get("id"), "status": "ready"}, {"$set": {"status": "committed", "committed_at": op_ts, "committed_by": user.get("username"), "committed_count": len(docs)}})
        await audit_log(user, "commit_card_pdf_import", "card_pdf_preview", preview.get("id"), None, {"category_id": category_id, "added": len(docs)})
        return {"ok": True, "added": len(docs), "category_id": category_id, "category_name": category.get("name"), "preview_id": preview.get("id")}

# ================= CARDS =================
@api.get("/cards")
async def list_cards(status_filter: Optional[str] = None, category_id: Optional[str] = None, q: Optional[str] = None,
                      date_from: Optional[str] = None, date_to: Optional[str] = None,
                      limit: int = 2000, offset: int = 0, user=Depends(require_perm("cards","stock"))):
    """قائمة الكروت مع الحالة الواضحة وبيانات البيع (فاتورة/عميل/سعر)."""
    query: Dict[str, Any] = {}
    if status_filter: query["status"] = status_filter
    if category_id: query["category_id"] = category_id
    if date_from or date_to:
        window: Dict[str, Any] = {}
        if date_from: window["$gte"] = date_from
        if date_to: window["$lte"] = date_to + "T23:59:59.999999+00:00" if len(date_to) == 10 else date_to
        query["created_at"] = window
    if q:
        term = str(q).strip()
        if term:
            numbers: List[str] = []
            # مطابقة أرقام الفواتير التي تحوي هذا الكرت
            async for sale in db.sales.find({"$or": [
                {"number": {"$regex": term, "$options": "i"}},
                {"customer_name": {"$regex": term, "$options": "i"}},
            ]}, {"items": 1}):
                for item in sale.get("items") or []:
                    numbers.extend([str(x).strip() for x in (item.get("card_numbers") or [])])
            async for free in db.free_card_sends.find({"$or": [
                {"number": {"$regex": term, "$options": "i"}},
                {"recipient_name": {"$regex": term, "$options": "i"}},
                {"recipient_phone": {"$regex": term, "$options": "i"}},
            ]}, {"card_number": 1}):
                if free.get("card_number"):
                    numbers.append(str(free.get("card_number")).strip())
            ids_matching = [row["id"] async for row in db.cards.find(
                {"$or": [
                    {"number": {"$regex": term, "$options": "i"}},
                    {"sale_number": {"$regex": term, "$options": "i"}},
                    {"customer_name": {"$regex": term, "$options": "i"}},
                ]}, {"id": 1})]
            ors: List[Dict[str, Any]] = [
                {"number": {"$regex": term, "$options": "i"}},
                {"sale_number": {"$regex": term, "$options": "i"}},
                {"customer_name": {"$regex": term, "$options": "i"}},
            ]
            if numbers:
                ors.append({"number": {"$in": numbers}})
            if ids_matching:
                ors.append({"id": {"$in": ids_matching}})
            query["$or"] = ors
    limit = min(max(int(limit or 2000), 1), 5000)
    offset = max(int(offset or 0), 0)
    items = await db.cards.find(query).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    items = [clean_doc(c) for c in items]
    try:
        items = await enrich_cards_with_sale_info(items)
    except Exception as exc:
        logger.warning("card enrichment failed: %s", exc)
    return items

@api.get("/sales/available-card-numbers")
async def available_card_numbers(category_id: str, limit: int = 2000, user=Depends(require_perm("sales", "cards", "stock"))):
    """Available numbered cards of one category, oldest first - used to auto-fill sale invoices."""
    category = await db.card_categories.find_one({"id": category_id})
    if not category:
        raise HTTPException(status_code=404, detail="الفئة غير موجودة")
    if is_balance_category(category):
        return {"category_id": category_id, "available": 0, "numbers": []}
    limit = min(max(int(limit or 2000), 1), 5000)
    query = {"category_id": category_id, "status": "available"}
    total = await db.cards.count_documents(query)
    rows = await db.cards.find(query, {"number": 1, "_id": 0}).sort("created_at", 1).limit(min(total, limit)).to_list(limit)
    numbers = [str(row.get("number") or "").strip() for row in rows if str(row.get("number") or "").strip()]
    return {"category_id": category_id, "available": total, "numbers": numbers}


@api.get("/cards/{card_id}/history")
async def card_history(card_id: str, user=Depends(require_perm("cards", "stock"))):
    """سجل حركة الكرت كاملاً: الإضافة، البيع، الإرجاع، الإرسال المجاني."""
    card = await db.cards.find_one({"id": card_id})
    if not card:
        raise HTTPException(status_code=404, detail="الكرت غير موجود")
    card = clean_doc(card)
    enriched = await enrich_cards_with_sale_info([card])
    events = await _card_history_events(card)
    return {"card": enriched[0], "events": events, "state_label": card_state_label(card.get("status"))}


async def _auth_token_user(token: Optional[str], authorization: Optional[str]) -> Dict[str, Any]:
    raw = (token or "").strip()
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    if not raw:
        raise HTTPException(status_code=401, detail="غير مصرح")
    try:
        payload = jwt.decode(raw, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="انتهت صلاحية الجلسة")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="جلسة غير صالحة")
    user = await db.users.find_one({"id": payload.get("sub")})
    if not user:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود")
    perms = set(user.get("permissions") or [])
    if user.get("role") != "admin" and not ({"cards", "stock", "cards.view", "free_cards"} & perms):
        raise HTTPException(status_code=403, detail="لا تملك صلاحية الكروت")
    return clean_doc(user)


@api.get("/cards/export.csv")
async def export_cards_csv(status_filter: Optional[str] = None, category_id: Optional[str] = None,
                           q: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
                           token: Optional[str] = None, authorization: Optional[str] = Header(default=None)):
    """تصدير الكروت وحالتها وبيانات بيعها إلى ملف Excel/CSV."""
    await _auth_token_user(token, authorization)
    rows = await list_cards(status_filter=status_filter, category_id=category_id, q=q,
                            date_from=date_from, date_to=date_to, limit=5000, offset=0,
                            user={"role": "admin"})
    header = ["رقم الكرت", "الفئة", "الحالة", "رقم فاتورة البيع", "العميل", "سعر البيع",
              "تاريخ البيع", "تاريخ التسجيل", "ملاحظات"]
    def _cell(value: Any) -> str:
        text = "" if value is None else str(value)
        text = text.replace('"', '""').replace("\r", " ").replace("\n", " ")
        return '"' + text + '"'
    lines = [",".join(_cell(h) for h in header)]
    for row in rows:
        note = ""
        if row.get("state_label") == "مجاني":
            note = "أُرسل إلى " + str(row.get("free_recipient") or "")
        elif str(row.get("sold_to") or "") == "public-net":
            note = "بيع مباشر بدون حساب"
        lines.append(",".join(_cell(v) for v in [
            row.get("number"), row.get("category_name"), row.get("state_label"),
            row.get("sale_number") or "", row.get("customer_name") or "",
            row.get("sold_price") if row.get("sold_price") is not None else "",
            str(row.get("sold_at") or "")[:10], str(row.get("created_at") or "")[:10], note,
        ]))
    csv_text = "\ufeff" + "\r\n".join(lines) + "\r\n"
    stamp = now_iso()[:10]
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="cards-{stamp}.csv"'},
    )

@api.post("/cards/add-numbers")
async def add_cards_numbers(data: CardsAddNumbersIn, user=Depends(require_perm("cards"))):
    cat = await db.card_categories.find_one({"id": data.category_id})
    if not cat:
        raise HTTPException(status_code=404, detail="الفئة غير موجودة")
    if is_balance_category(cat):
        raise HTTPException(status_code=400, detail="فئة رصيد مالية وليست فئة كروت")
    # normalize
    seen = set()
    valid = []
    duplicates = []
    invalid = []
    for raw in data.numbers:
        n = (raw or "").strip()
        if not n: continue
        if not n.replace("-", "").replace(" ", "").isdigit() or len(n) < 4:
            invalid.append(n); continue
        if n in seen:
            duplicates.append(n); continue
        seen.add(n)
        # check DB
        exists = await db.cards.find_one({"number": n})
        if exists:
            duplicates.append(n); continue
        valid.append(n)
    docs = []
    op_ts = now_iso()
    for n in valid:
        docs.append({
            "id": str(uuid.uuid4()),
            "number": n,
            "category_id": data.category_id,
            "category_name": cat.get("name"),
            "status": "available",
            "type": "numbered",
            "created_at": op_ts,
            "created_by": user.get("username"),
        })
    if docs:
        await db.cards.insert_many(docs)
        await db.stock_ops.insert_one({
            "id": str(uuid.uuid4()),
            "category_id": data.category_id,
            "category_name": cat.get("name"),
            "kind": "add_numbered",
            "quantity": len(docs),
            "description": f"إضافة {len(docs)} كرت مرقم بدون فاتورة مشتريات",
            "user_id": user.get("id"),
            "username": user.get("username"),
            "created_at": op_ts,
        })
    await audit_log(user, "add_cards", "cards", data.category_id, None, {"added": len(docs)})
    return {"added": len(docs), "duplicates": duplicates, "invalid": invalid}

@api.post("/cards/add-quantity")
async def add_cards_qty(data: CardsAddQtyIn, user=Depends(require_perm("cards"))):
    cat = await db.card_categories.find_one({"id": data.category_id})
    if not cat:
        raise HTTPException(status_code=404, detail="الفئة غير موجودة")
    if is_balance_category(cat):
        raise HTTPException(status_code=400, detail="استخدم شاشة إدارة مخزون الرصيد لإضافة مبلغ")
    doc = await db.stock.find_one({"category_id": data.category_id})
    if doc:
        await db.stock.update_one({"category_id": data.category_id}, {"$inc": {"total": data.quantity}})
    else:
        await db.stock.insert_one({
            "id": str(uuid.uuid4()),
            "category_id": data.category_id,
            "category_name": cat.get("name"),
            "total": data.quantity,
            "sold": 0,
            "used": 0,
            "created_at": now_iso(),
        })
    await db.stock_ops.insert_one({
        "id": str(uuid.uuid4()),
        "category_id": data.category_id,
        "category_name": cat.get("name"),
        "kind": "add_quantity",
        "quantity": int(data.quantity),
        "description": f"إضافة {data.quantity} كرت (كمية) بدون فاتورة مشتريات",
        "user_id": user.get("id"),
        "username": user.get("username"),
        "created_at": now_iso(),
    })
    return {"ok": True, "added": data.quantity}

@api.post("/stock/balance/add")
@idempotent_operation("balance_stock_add", "stock_ops")
async def add_balance_stock(data: BalanceStockAddIn, user=Depends(require_perm("stock"))):
    category = await get_balance_category()
    number = (data.number or "").strip() or await next_gwd_number()
    if await db.stock_ops.find_one({"number": number}):
        raise HTTPException(status_code=409, detail="رقم العملية مستخدم مسبقاً")
    when = now_iso()
    stock = await db.stock.find_one({"category_id": category["id"]})
    old_total = float((stock or {}).get("total", 0) or 0)
    op = {
        "id": str(uuid.uuid4()), "number": number, "category_id": category["id"],
        "category_name": category.get("name", BALANCE_CATEGORY_NAME), "kind": "balance_add",
        "amount": float(data.amount), "quantity": float(data.amount), "description": (data.description or "").strip(),
        "user_id": user.get("id"), "username": user.get("username"), "created_at": when,
        "balance_before": old_total, "balance_after": old_total + float(data.amount),
        "idempotency_key": data.idempotency_key,
    }
    try:
        if stock:
            await db.stock.update_one({"category_id": category["id"]}, {"$inc": {"total": float(data.amount)}})
        else:
            await db.stock.insert_one({"id": str(uuid.uuid4()), "category_id": category["id"], "category_name": category.get("name", BALANCE_CATEGORY_NAME), "total": float(data.amount), "sold": 0, "used": 0, "created_at": when})
        await db.stock_ops.insert_one(op)
    except Exception:
        if stock:
            await db.stock.update_one({"category_id": category["id"]}, {"$inc": {"total": -float(data.amount)}})
        else:
            await db.stock.delete_one({"category_id": category["id"], "total": float(data.amount), "sold": 0})
        raise
    await audit_log(user, "add_balance_stock", "stock", category["id"], None, {"number": number, "amount": float(data.amount)})
    return clean_doc(op)

@api.get("/stock/balance/operations")
async def balance_stock_operations(start: Optional[str] = None, end: Optional[str] = None, user=Depends(require_perm("stock"))):
    category = await get_balance_category()
    query: Dict[str, Any] = {"category_id": category["id"]}
    if start or end:
        query["$expr"] = mongo_business_date_expr(start, end)
    ops = await db.stock_ops.find(query).sort("created_at", -1).limit(2000).to_list(2000)
    return [clean_doc(x) for x in ops]

@api.get("/cards/search/{number}")
async def find_card(number: str, user=Depends(require_perm("cards"))):
    card = await db.cards.find_one({"number": number})
    if not card:
        raise HTTPException(status_code=404, detail="الكرت غير موجود")
    return clean_doc(card)

@api.put("/cards/{card_id}/status")
async def update_card_status(card_id: str, new_status: str, user=Depends(require_perm("cards"))):
    await db.cards.update_one({"id": card_id}, {"$set": {"status": new_status}})
    return {"ok": True}

class CardEditIn(BaseModel):
    number: Optional[str] = None
    category_id: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None

@api.put("/cards/{card_id}")
async def edit_card(card_id: str, data: CardEditIn, user=Depends(require_perm("cards"))):
    card = await db.cards.find_one({"id": card_id})
    if not card:
        raise HTTPException(status_code=404, detail="غير موجود")
    if card.get("status") in ("sold", "used") and (data.number or data.category_id):
        raise HTTPException(status_code=400, detail="لا يمكن تعديل رقم/فئة كرت مباع")
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if data.number and data.number != card.get("number"):
        exists = await db.cards.find_one({"number": data.number, "id": {"$ne": card_id}})
        if exists:
            raise HTTPException(status_code=400, detail="رقم الكرت مكرر")
    if data.category_id:
        cat = await db.card_categories.find_one({"id": data.category_id})
        if cat: update["category_name"] = cat.get("name")
    await db.cards.update_one({"id": card_id}, {"$set": update})
    await audit_log(user, "update", "card", card_id, card, update)
    return {"ok": True}

@api.delete("/cards/{card_id}")
async def delete_card(card_id: str, user=Depends(require_perm("cards"))):
    card = await db.cards.find_one({"id": card_id})
    if not card:
        raise HTTPException(status_code=404, detail="غير موجود")
    if card.get("status") == "sold":
        await db.cards.update_one({"id": card_id}, {"$set": {"status": "cancelled"}})
        await audit_log(user, "cancel", "card", card_id)
        return {"ok": True, "action": "cancelled"}
    await db.cards.delete_one({"id": card_id})
    await audit_log(user, "delete", "card", card_id)
    return {"ok": True, "action": "deleted"}


# Change customer password (admin)
class PasswordIn(BaseModel):
    password: str

@api.post("/customers/{cid}/password")
async def admin_set_customer_password(cid: str, data: PasswordIn, user=Depends(require_perm("customers"))):
    if len(data.password) < 4:
        raise HTTPException(status_code=400, detail="كلمة المرور قصيرة جداً")
    cust = await db.customers.find_one({"id": cid})
    if not cust:
        raise HTTPException(status_code=404, detail="غير موجود")
    await db.customers.update_one({"id": cid}, {"$set": {"password": data.password}})
    await audit_log(user, "reset_customer_password", "customer", cid, None, {"name": cust.get("name", "")})
    # WhatsApp URL for admin to click and notify the customer
    from urllib.parse import quote
    wa_phone = "".join(ch for ch in (cust.get("phone") or "") if ch.isdigit()).lstrip("0")
    if wa_phone and not wa_phone.startswith("967"):
        wa_phone = "967" + wa_phone
    body = await _render_message_template("password_reset", {
        "name": cust.get("name", ""), "phone": cust.get("phone", ""),
        "password": data.password, "company": COMPANY_NAME,
    })
    wa_url = f"https://wa.me/{wa_phone}?text={quote(body)}" if wa_phone and await _message_channel_enabled("password_reset", "whatsapp") and body else ""
    return {"ok": True, "whatsapp_url": wa_url}


# تسوية حساب العميل: تصحيح خطأ في الرصيد بمبلغ محدد (له / عليه) وبتاريخ محدد
class CustomerSettlementIn(BaseModel):
    amount: float
    direction: str  # "debit" = عليه (يزيد المديونية) | "credit" = له (يقلل المديونية)
    date: Optional[str] = None
    description: Optional[str] = None
    idempotency_key: Optional[str] = None


@api.post("/customers/{cid}/settlement")
async def settle_customer_account(cid: str, data: CustomerSettlementIn, user=Depends(require_perm("customers"))):
    """تسوية حساب (تصحيح أرصدة) — يُسجَّل البند في كشف الحساب بتاريخ التسوية نفسه."""
    amount = abs(_numeric_amount(data.amount, 0.0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="أدخل مبلغ التسوية")
    direction = str(data.direction or "").strip().lower()
    if direction not in ("debit", "credit"):
        raise HTTPException(status_code=400, detail="حدد نوع التسوية: له أو عليه")
    cust = await db.customers.find_one({"id": cid})
    if not cust:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    if data.idempotency_key:
        existing = await db.settlements.find_one({"idempotency_key": data.idempotency_key})
        if existing:
            return clean_doc(existing)
    when = business_timestamp(data.date)
    sign = amount if direction == "debit" else -amount
    label = (data.description or "").strip() or ("تسوية حساب (عليه)" if direction == "debit" else "تسوية حساب (له)")
    balance_before = _numeric_amount(cust.get("balance"), 0.0)
    number = await next_gwd_number()
    balance_after = await _adjust_party_balance("customer", cid, sign, number, label, when=when)
    if balance_after is None:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    doc = {
        "id": str(uuid.uuid4()), "number": number, "type": "customer_settlement",
        "party_type": "customer", "party_id": cid, "party_name": cust.get("name") or "",
        "amount": amount, "direction": direction, "description": label,
        "balance_before": balance_before, "balance_after": balance_after,
        "user_id": user["id"], "username": user.get("username"),
        "status": "active", "idempotency_key": data.idempotency_key,
        "created_at": when, "operation_at": now_iso(),
    }
    try:
        await db.settlements.insert_one(doc)
    except Exception:
        await _remove_ledger_by_op("customer", cid, number)
        raise
    await audit_log(user, "customer_settlement", "customer", cid,
                    {"balance": balance_before},
                    {"balance": balance_after, "amount": amount, "direction": direction, "date": when})
    return clean_doc(doc)


# Customer self-service password change
class CustomerChangePwd(BaseModel):
    phone: str
    current_password: str
    new_password: str

@api.post("/public/customer/change-password")
async def customer_change_password(data: CustomerChangePwd):
    if len(data.new_password) < 4:
        raise HTTPException(status_code=400, detail="كلمة المرور الجديدة قصيرة جداً (4 أحرف على الأقل)")
    # بحث متسامح مع صيغ الرقم: محلي / دولي / بصفر بادئ / مع +967
    _raw = (data.phone or "").strip()
    _digits = "".join(ch for ch in _raw if ch.isdigit())
    _local = _digits.lstrip("0")
    if _local.startswith("967") and len(_local) > 9:
        _local = _local[3:]
    _variants = []
    for _v in [_raw, _digits, _local, "967" + _local, "0" + _local, _digits[-9:]]:
        if _v and _v not in _variants:
            _variants.append(_v)
    customer = await db.customers.find_one({"phone": {"$in": _variants}})
    if not customer:
        raise HTTPException(status_code=404, detail="لاتمتلك حساب بهذا الرقم، عليك بانشاء حساب أولاً")
    if customer.get("password") != data.current_password:
        raise HTTPException(status_code=401, detail="كلمة المرور الحالية غير صحيحة")
    await db.customers.update_one({"id": customer["id"]}, {"$set": {"password": data.new_password}})
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()), "user_id": customer["id"], "username": customer["name"],
        "action": "self_change_password", "entity": "customer", "entity_id": customer["id"],
        "created_at": now_iso(),
    })
    _pw_title = "تغيير كلمة المرور"
    _pw_msg = f"قام العميل {customer.get('name','')} بتغيير كلمة المرور الخاصة به. الهاتف: {customer.get('phone','')}"
    _pw_id = str(uuid.uuid4())
    await db.notifications.insert_one({
        "id": _pw_id, "title": _pw_title,
        "message": _pw_msg,
        "type": "info", "read": False, "created_at": now_iso(),
    })
    await _notify_push(_pw_id, _pw_title, _pw_msg, "info", {"category": "customer_password"})
    return {"ok": True}


# Forgot password - lookup and return WhatsApp payload
class ForgotIn(BaseModel):
    phone: str

@api.post("/public/customer/forgot-password")
async def customer_forgot(data: ForgotIn):
    """طلب استعادة كلمة المرور: يُرسل الطلب للإدارة فقط دون أي رسالة نصية أو واتساب.
    كلمة المرور الجديدة تُنشأ عند موافقة الإدارة وتُرسل إلى رقم الحساب نفسه."""
    phone = (data.phone or "").strip()
    customer = await db.customers.find_one({"phone": phone})
    if not customer:
        raise HTTPException(status_code=404, detail="لاتمتلك حساب بهذا الرقم، عليك بانشاء حساب أولاً")
    now = now_iso()
    current = str(customer.get("password_reset_status") or "")
    if current != "requested":
        await db.customers.update_one({"id": customer["id"]}, {"$set": {
            "password_reset_status": "requested",
            "password_reset_requested_at": now,
            "updated_at": now,
        }})
        msg = (
            f"طلب استعادة كلمة المرور\n"
            f"الاسم: {customer.get('name') or ''}\n"
            f"الهاتف: {customer.get('phone') or ''}\n"
            f"العنوان: {customer.get('address') or ''}\n"
            f"تاريخ ووقت الطلب: {now}"
        )
        nid = str(uuid.uuid4())
        await db.notifications.insert_one({
            "id": nid, "title": "طلب استعادة كلمة المرور", "message": msg,
            "type": "warning", "category": "password_reset_request",
            "ref_id": customer["id"], "read": False, "created_at": now,
            "details": {"category": "password_reset_request",
                        "operation": "password_reset_request",
                        "customer_id": customer["id"], "phone": customer.get("phone"),
                        "name": customer.get("name") or "", "requested_at": now},
        })
        try:
            await _notify_push(nid, "طلب استعادة كلمة المرور", msg, "warning",
                               {"category": "password_reset_request", "customer_id": customer["id"]})
        except Exception:
            pass
    return {
        "ok": True,
        "message": "تم إرسال طلبك بنجاح، سيصلك كلمة المرور الجديدة إلى رقم هاتفك",
        "name": customer.get("name"), "phone": customer.get("phone"),
        "address": customer.get("address", ""),
    }

@api.get("/password-reset-requests")
async def list_password_reset_requests(user=Depends(require_perm("customers"))):
    """طلبات استعادة كلمة المرور المعلّقة."""
    items = await db.customers.find({
        "password_reset_status": "requested",
    }).sort("password_reset_requested_at", -1).limit(500).to_list(500)
    return {"items": [{
        "id": c.get("id"), "name": c.get("name") or "", "phone": c.get("phone") or "",
        "address": c.get("address") or "",
        "requested_at": c.get("password_reset_requested_at") or "",
    } for c in items]}

class PasswordResetApproveIn(BaseModel):
    channel: Optional[str] = None

@api.post("/password-reset-requests/{cid}/approve")
async def approve_password_reset(cid: str, data: PasswordResetApproveIn, user=Depends(require_perm("customers"))):
    """موافقة الإدارة: توليد كلمة مرور جديدة وإرسالها للعميل عبر القناة المختارة."""
    channel = str(data.channel or "").strip().lower()
    if channel not in ("whatsapp", "sms"):
        raise HTTPException(status_code=400, detail="اختر قناة إرسال كلمة المرور: واتساب أو رسالة نصية")
    customer = await db.customers.find_one({"id": cid})
    if not customer:
        raise HTTPException(status_code=404, detail="الحساب غير موجود")
    if str(customer.get("password_reset_status") or "") != "requested":
        raise HTTPException(status_code=400, detail="لا يوجد طلب استعادة كلمة مرور معلّق لهذا الحساب")
    new_password = await unique_random_password()
    now = now_iso()
    await db.customers.update_one({"id": cid}, {"$set": {
        "password": new_password,
        "password_reset_status": "approved",
        "password_reset_approved_at": now,
        "password_reset_approved_by": user.get("username"),
        "password_reset_channel": channel,
        "updated_at": now,
    }})
    await audit_log(user, "approve_password_reset", "customer", cid, None,
                    {"name": customer.get("name"), "channel": channel})
    await db.notifications.update_many({"category": "password_reset_request", "ref_id": cid},
                                       {"$set": {"read": True, "read_at": now}})
    body = await _render_message_template("password_reset", {
        "name": customer.get("name", ""), "phone": customer.get("phone", ""),
        "password": new_password, "company": COMPANY_NAME,
    })
    phone_digits = "".join(ch for ch in str(customer.get("phone") or "") if ch.isdigit())
    wa_phone = phone_digits.lstrip("0")
    if wa_phone and not wa_phone.startswith("967"):
        wa_phone = "967" + wa_phone
    from urllib.parse import quote
    wa_url = f"https://wa.me/{wa_phone}?text={quote(body)}" if channel == "whatsapp" and wa_phone else ""
    sms_url = f"sms:+{wa_phone}?body={quote(body)}" if channel == "sms" and wa_phone else ""
    return {"ok": True, "channel": channel, "phone": customer.get("phone"),
            "message": body, "whatsapp_url": wa_url, "sms_url": sms_url}

@api.post("/password-reset-requests/{cid}/reject")
async def reject_password_reset(cid: str, user=Depends(require_perm("customers"))):
    customer = await db.customers.find_one({"id": cid})
    if not customer:
        raise HTTPException(status_code=404, detail="الحساب غير موجود")
    now = now_iso()
    await db.customers.update_one({"id": cid}, {"$set": {
        "password_reset_status": "rejected",
        "password_reset_rejected_at": now,
        "password_reset_rejected_by": user.get("username"),
        "updated_at": now,
    }})
    await db.notifications.update_many({"category": "password_reset_request", "ref_id": cid},
                                       {"$set": {"read": True, "read_at": now}})
    await audit_log(user, "reject_password_reset", "customer", cid, None, {"name": customer.get("name")})
    return {"ok": True}

# Public account registration request - only creates a pending request record
class RegisterRequest(BaseModel):
    full_name: str
    phone: str
    address: str
    account_type: str = "customer"

@api.post("/public/customer/register-request")
async def register_request(data: RegisterRequest):
    name = (data.full_name or "").strip()
    phone = (data.phone or "").strip()
    address = (data.address or "").strip()
    account_type = (data.account_type or "customer").strip().lower()
    if len(name) < 6:
        raise HTTPException(status_code=400, detail="الاسم الرباعي مطلوب")
    if len(name.split()) < 4:
        raise HTTPException(status_code=400, detail="الرجاء إدخال الاسم الرباعي كاملاً (أربعة أسماء)")
    _bad_chars = [c for c in name if not (('\u0600' <= c <= '\u06FF') or c in " '\u2019\u0640-")]
    if _bad_chars:
        raise HTTPException(status_code=400, detail="يُقبل الاسم بالأحرف العربية فقط")
    if not phone or len(phone) < 7 or not phone.replace("+","").isdigit():
        raise HTTPException(status_code=400, detail="رقم الهاتف غير صحيح")
    if len(address) < 2:
        raise HTTPException(status_code=400, detail="العنوان مطلوب")
    if account_type not in {"customer", "pos"}:
        raise HTTPException(status_code=400, detail="نوع الحساب غير صحيح")
    existing = await db.customers.find_one({"phone": phone}, {"_id": 1})
    if existing:
        raise HTTPException(status_code=400, detail="هذا الرقم مرتبط بحساب آخر في شبكة جواد نت. إذا كان الرقم خاصتك اطلب استعادة كلمة المرور، وإن لم يكن خاصتك سجّل برقم آخر.")
    # ===== إنشاء فوري: يُنشأ الحساب مباشرة كـ«غير موثّق» =====
    # النوع المختار (عميل / نقطة بيع) يُحفظ للعلم فقط ولا يُطبَّق حتى توثيق الإدارة.
    _pwd = await unique_random_password()
    _customer_id = str(uuid.uuid4())
    _created_at = now_iso()
    _customer_doc = {
        "id": _customer_id, "name": name, "phone": phone, "address": address,
        "password": _pwd, "credit_limit": 0, "opening_balance": 0, "balance": 0,
        "status": "active", "customer_type": "customer",
        "requested_type": account_type, "origin": "portal_auto", "verified": False,
        "verification_status": "not_requested",
        "notes": "تسجيل ذاتي من بوابة العميل — بانتظار طلب التوثيق",
        "created_at": _created_at, "created_by": "portal",
    }
    await db.customers.insert_one(_customer_doc)
    _customer_doc["alternative_number"] = await _ensure_customer_alternative_number(_customer_doc)
    doc = {
        "id": str(uuid.uuid4()), "full_name": name, "phone": phone,
        "address": address, "account_type": account_type, "status": "auto_created",
        "customer_id": _customer_id, "created_at": _created_at,
    }
    await db.register_requests.insert_one(doc)
    notification_settings, _ = await _app_channel_settings()
    if notification_settings.get("enabled", True) and notification_settings.get("in_app_enabled", True) and notification_settings.get("account_requests_enabled", True) and await _message_channel_enabled("account_request", "in_app"):
        request_message = (
            "تم إنشاء حساب جديد في بوابة العميل\n"
            f"الاسم: {name}\nالهاتف: {phone}\nالعنوان: {address}\n"
            f"نوع الحساب المطلوب: {'نقطة بيع' if account_type == 'pos' else 'عميل'}\n"
            f"الحالة: غير موثّق\nتاريخ ووقت الإنشاء: {_created_at}"
        )
        _req_id = str(uuid.uuid4())
        await db.notifications.insert_one({
            "id": _req_id, "title": "إنشاء حساب جديد",
            "message": request_message,
            "type": "info", "category": "account_created", "ref_id": doc["id"],
            "read": False, "created_at": _created_at,
            "details": {"category": "account_created", "operation": "account_created",
                        "customer_id": _customer_id, "name": name, "phone": phone,
                        "address": address, "account_type": account_type,
                        "created_at": _created_at},
        })
        # إرسال فوري إلى الأجهزة حتى والتطبيق مغلق
        await _notify_push(_req_id, "إنشاء حساب جديد", request_message, "info",
                           {"category": "account_created", "operation": "account_created", "ref_id": doc["id"], "phone": phone, "name": name})
    return {"ok": True, "customer_id": _customer_id, "name": name, "phone": phone,
            "password": _pwd, "pending_verification": True, "requested_type": account_type}


# Card order attempts log
@api.get("/reports/card-order-log")
async def card_order_log(user=Depends(require_perm("reports"))):
    items = await db.card_order_attempts.find().sort("created_at", -1).limit(2000).to_list(2000)
    return [clean_doc(a) for a in items]


@api.get("/reports/login-attempts")
async def login_attempts_report(user=Depends(require_perm("reports"))):
    """تقرير محاولات الدخول الفاشلة (بوابة العميل + دخول المستخدمين).

    تُحفظ المحاولات 90 يوماً ثم تُمسح تلقائياً عند أول طلب بعد المدة.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    try:
        await db.card_order_attempts.delete_many({"created_at": {"$lt": cutoff}})
    except Exception:
        pass
    items = await db.card_order_attempts.find(
        {"status": {"$in": ["login_failed", "rejected_not_found", "login_device", "login_disabled"]}}
    ).sort("created_at", -1).limit(1000).to_list(1000)
    rows = []
    for a in items:
        rows.append({
            "id": a.get("id"),
            "source": "دخول المستخدمين" if a.get("kind") == "user" else "بوابة العميل",
            "identifier": a.get("phone") or "",
            "name": a.get("customer_name") or "",
            "password_try": a.get("attempt_password") or "",
            "reason": a.get("reason") or "",
            "created_at": a.get("created_at") or "",
        })
    return rows

# Electronic sales report (public order source)
@api.get("/reports/electronic-sales")
async def electronic_sales(user=Depends(require_perm("reports"))):
    items = await db.sales.find({"source": "public_order", "status": "active"}).sort("created_at", -1).limit(2000).to_list(2000)
    return [clean_doc(s) for s in items]


# ================= STOCK =================
@api.get("/stock")
async def stock_report(start: Optional[str] = None, end: Optional[str] = None, user=Depends(require_perm("stock"))):
    cats = await db.card_categories.find().to_list(500)
    period_active = bool(start or end)
    def _in_range(ts):
        return timestamp_in_business_range(ts, start, end)
    # Preload sales in period once for quantity-sold movement (non-numbered items).
    sales_in_period = []
    if period_active:
        sales_in_period = await db.sales.find({"status": "active", "$expr": mongo_business_date_expr(start, end)}).to_list(20000)
    result = []
    for cat in cats:
        cat = clean_doc(cat)
        # numbered cards
        avail = await db.cards.count_documents({"category_id": cat["id"], "status": "available"})
        sold = await db.cards.count_documents({"category_id": cat["id"], "status": "sold"})
        used = await db.cards.count_documents({"category_id": cat["id"], "status": "used"})
        free = await db.cards.count_documents({"category_id": cat["id"], "status": FREE_CARD_STATUS})
        total_num = await db.cards.count_documents({"category_id": cat["id"]})
        # qty stock
        qs = await db.stock.find_one({"category_id": cat["id"]})
        qty_total = (qs or {}).get("total", 0)
        qty_sold = (qs or {}).get("sold", 0)
        threshold = cat.get("low_stock_threshold", 20)
        is_balance = is_balance_category(cat)
        # Money held in the balance stock must remain visible as an amount, but
        # it is not a card/quantity and must not inflate the inventory total.
        available_total = 0 if is_balance else avail + max(0, qty_total - qty_sold)
        entry = {
            "category_id": cat["id"],
            "category_name": cat["name"],
            "kind": cat.get("kind", "card"),
            "is_balance": is_balance_category(cat),
            "sale_price": cat.get("sale_price", 0),
            "numbered": {"total": total_num, "available": avail, "sold": sold, "used": used},
            "quantity": {"total": qty_total, "sold": qty_sold, "available": max(0, qty_total - qty_sold)},
            "available_total": available_total,
            "low_stock": (not is_balance) and available_total <= threshold,
            "threshold": threshold,
        }
        if period_active:
            added_numbered = await db.cards.count_documents({"category_id": cat["id"], "$expr": mongo_business_date_expr(start, end, "created_at")})
            sold_numbered = await db.cards.count_documents({"category_id": cat["id"], "status": {"$in": ["sold", "used"]}, "$expr": mongo_business_date_expr(start, end, "sold_at")})
            qadd_ops = await db.stock_ops.find({"category_id": cat["id"], "kind": {"$in": ["add_quantity"]}}).to_list(5000)
            qty_added = sum(o.get("quantity", 0) for o in qadd_ops if _in_range(o.get("created_at")))
            qty_sold_period = 0
            for s in sales_in_period:
                for it in (s.get("items") or []):
                    if it.get("category_id") == cat["id"] and not it.get("use_numbered"):
                        qty_sold_period += it.get("quantity", 0)
            entry["period"] = {
                "added": added_numbered + qty_added,
                "sold": sold_numbered + qty_sold_period,
                "added_numbered": added_numbered,
                "sold_numbered": sold_numbered,
                "added_quantity": qty_added,
                "sold_quantity": qty_sold_period,
            }
        result.append(entry)
    return result


# ================= SALES =================
async def _adjust_party_balance(party_type: str, party_id: str, amount: float, op_number: str, description: str, when: Optional[str] = None):
    """Positive amount = increase debt to us (sale). Negative = decrease debt (receipt).

    `when` is the business date of the source document (voucher / transfer). When it is
    supplied the statement row is stamped with that date instead of the moment the
    document happened to be entered, so a back-dated document keeps its own date.
    """
    collection = db.customers if party_type == "customer" else db.suppliers
    updated = await collection.find_one_and_update(
        {"id": party_id},
        {"$inc": {"balance": float(amount)}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        return None
    new_balance = _numeric_amount(updated.get("balance"), 0.0)
    try:
        await db.ledger.insert_one({
            "id": str(uuid.uuid4()),
            "party_type": party_type, "party_id": party_id,
            "op_number": op_number, "description": description,
            "debit": amount if amount > 0 else 0,
            "credit": abs(amount) if amount < 0 else 0,
            "balance": new_balance,
            "created_at": when or now_iso(),
        })
    except Exception:
        await collection.update_one({"id": party_id}, {"$inc": {"balance": -float(amount)}})
        raise
    return new_balance


async def _remove_ledger_by_op(party_type: str, party_id: str, op_number: str):
    """Delete ALL ledger entries linked to an operation (used on edit/delete).
    Keeps the statement clean of 'تعديل/حذف/عكس' entries. Returns the net delta removed
    so the caller can update the party balance accordingly."""
    if not op_number: return 0.0
    entries = await db.ledger.find({"party_type": party_type, "party_id": party_id, "op_number": op_number}).to_list(500)
    delta = sum(_numeric_amount(e.get("debit"), 0.0) - _numeric_amount(e.get("credit"), 0.0) for e in entries)
    collection = db.customers if party_type == "customer" else db.suppliers
    if delta:
        result = await collection.update_one({"id": party_id}, {"$inc": {"balance": -delta}})
        if result.matched_count != 1:
            raise RuntimeError("تعذر عكس رصيد الحساب المرتبط بالقيد")
    try:
        if entries:
            await db.ledger.delete_many({"party_type": party_type, "party_id": party_id, "op_number": op_number})
    except Exception:
        if delta:
            await collection.update_one({"id": party_id}, {"$inc": {"balance": delta}})
        raise
    return delta


async def _reject_duplicate_operation(
    collection,
    query: Dict[str, Any],
    amount: float,
    label: str,
    allow_duplicate: bool = False,
    amount_field: str = "amount",
):
    """Require an explicit second confirmation for same-account/same-amount operations."""
    if allow_duplicate:
        return
    docs = await collection.find({
        **query,
        "status": {"$in": ["active", "done"]},
    }).sort("created_at", -1).limit(80).to_list(80)
    target = _numeric_amount(amount, 0.0)
    for existing in docs:
        existing_amount = _numeric_amount(existing.get(amount_field), float("nan"))
        if existing_amount != existing_amount:
            continue
        if abs(existing_amount - target) <= 0.0001:
            number = existing.get("number") or existing.get("id") or "—"
            raise HTTPException(
                status_code=409,
                detail=f"توجد {label} سابقة بنفس المبلغ لنفس الحساب (رقم العملية {number}). هل تريد المتابعة؟",
            )


async def _reject_duplicate_financial_operation(
    account_type: str,
    account_id: Optional[str],
    amount: float,
    label: str,
    allow_duplicate: bool = False,
):
    """Require explicit approval only for a same-account/same-amount operation in two minutes."""
    if allow_duplicate or not account_id:
        return
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=DUPLICATE_OPERATION_WINDOW_SECONDS)
    account_collection = {
        "customer": db.customers,
        "supplier": db.suppliers,
        "expense": db.expense_accounts,
    }.get(account_type)
    account = await account_collection.find_one({"id": account_id}) if account_collection is not None else None
    account_name = (account or {}).get("name") or "الحساب المرتبط"
    account_phone = (account or {}).get("phone") or ""

    candidates = []
    if account_type in ("customer", "supplier"):
        candidates.extend([
            (db.sales, {"customer_id": account_id}, "فاتورة مبيعات", "total"),
            (db.purchases, {"supplier_id": account_id}, "فاتورة مشتريات", "total"),
            (db.receipts, {"party_type": account_type, "party_id": account_id}, "سند", "amount"),
            (db.transfers, {"$or": [
                {"source_type": account_type, "source_id": account_id},
                {"dest_type": account_type, "dest_id": account_id},
                {"sender_id": account_id},
                {"recipient_id": account_id},
            ]}, "تحويل", "amount"),
        ])
    elif account_type == "expense":
        candidates.append((db.expenses, {"account_id": account_id}, "مصروف", "amount"))

    target = _numeric_amount(amount, 0.0)
    for collection, query, operation_label, amount_field in candidates:
        docs = await collection.find({**query, "status": {"$in": ["active", "done"]}}).sort("operation_at", -1).limit(200).to_list(200)
        for existing in docs:
            existing_at = parse_timestamp_utc(existing.get("operation_at"))
            if not existing_at or existing_at < cutoff or existing_at > now:
                continue
            existing_amount = _numeric_amount(existing.get(amount_field), float("nan"))
            if existing_amount != existing_amount:
                continue
            if abs(existing_amount - target) <= 0.0001:
                number = existing.get("number") or existing.get("id") or "—"
                previous_at = existing_at.astimezone(APP_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
                phone_suffix = f" — {account_phone}" if account_phone else ""
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"توجد {operation_label} سابقة بنفس المبلغ ولنفس الحساب خلال آخر دقيقتين "
                        f"قبل حفظ {label}. المبلغ: {target:,.2f}. الحساب: {account_name}{phone_suffix}. "
                        f"رقم العملية: {number}. وقت العملية السابقة: {previous_at}. هل تريد المتابعة؟"
                    ),
                )


async def _validate_sale_inventory(items: list, old_items: Optional[list] = None):
    """Validate the complete sale before mutating stock; old items are treated as releasable on edit."""
    old_items = old_items or []
    old_numbered = set()
    old_numbered_by_cat: Dict[str, int] = {}
    old_qty_by_cat: Dict[str, int] = {}
    for item in old_items:
        cat_id = item.get("category_id")
        numbers = set(item.get("card_numbers") or [])
        old_numbered.update(numbers)
        old_numbered_by_cat[cat_id] = old_numbered_by_cat.get(cat_id, 0) + len(numbers)
        residual = max(int(item.get("quantity", 0) or 0) - len(numbers), 0)
        old_qty_by_cat[cat_id] = old_qty_by_cat.get(cat_id, 0) + residual

    reserved_numbers = set()
    reserved_by_cat: Dict[str, int] = {}
    quantity_by_cat: Dict[str, int] = {}
    for item in items:
        if item.use_numbered and item.card_numbers:
            for number in item.card_numbers:
                if number in reserved_numbers:
                    raise HTTPException(status_code=400, detail=f"الكرت {number} مكرر في الفاتورة")
                card = await db.cards.find_one({"number": number})
                if not card or (card.get("status") != "available" and number not in old_numbered):
                    raise HTTPException(status_code=400, detail=f"الكرت {number} غير متوفر")
                reserved_numbers.add(number)
                cat_id = card.get("category_id") or item.category_id
                reserved_by_cat[cat_id] = reserved_by_cat.get(cat_id, 0) + 1
        else:
            quantity_by_cat[item.category_id] = quantity_by_cat.get(item.category_id, 0) + int(item.quantity)

    for cat_id, required in quantity_by_cat.items():
        stock = await db.stock.find_one({"category_id": cat_id})
        quantity_available = max((stock or {}).get("total", 0) - (stock or {}).get("sold", 0), 0)
        quantity_available += old_qty_by_cat.get(cat_id, 0)
        numbered_available = await db.cards.count_documents({"category_id": cat_id, "status": "available"})
        numbered_available += old_numbered_by_cat.get(cat_id, 0)
        numbered_available -= reserved_by_cat.get(cat_id, 0)
        if quantity_available + max(numbered_available, 0) < required:
            raise HTTPException(status_code=400, detail="الكمية غير متوفرة للفئة")


# ================= WALLET TRANSFERS (public) =================
class TransferLookupIn(BaseModel):
    phone: str
    password: str
    recipient_phone: str
    amount: float = Field(gt=0)

class TransferConfirmIn(TransferLookupIn):
    idempotency_key: str = Field(min_length=1, max_length=160)
    description: Optional[str] = None
    allow_duplicate: bool = False
    number: Optional[str] = None

def _account_type(account: dict) -> str:
    return str((account or {}).get("customer_type") or "customer").strip().lower()

def _transfer_commission(sender: dict, amount: float, recipient: Optional[dict] = None) -> float:
    """Calculate commission from verified sender/recipient account documents."""
    sender = sender or {}
    if _account_type(sender) == "pos" and _account_type(recipient) == "pos":
        return 0.0
    configured = sender.get("transfer_percentage")
    if configured is None:
        configured = 10.0 if _account_type(sender) == "pos" else 0.0
    percentage = max(0.0, min(100.0, _numeric_amount(configured, 0.0)))
    return round(_numeric_amount(amount, 0.0) * percentage / 100.0, 2)

def _transfer_financials(sender: dict, recipient: dict, amount: float) -> Dict[str, float]:
    """Return the only valid financial values for a verified transfer."""
    amount = _numeric_amount(amount, 0.0)
    commission = _transfer_commission(sender, amount, recipient)
    sender_debit = amount - commission if _account_type(sender) == "pos" else amount + commission
    return {"amount": amount, "commission": commission, "sender_debit": sender_debit, "recipient_credit": amount}

def _require_pos_transfer_sender(sender: dict) -> dict:
    """Allow public subscriber transfers only for a real POS account.

    The type is read from the customer document returned by the verified
    phone/password lookup. Client-provided fields are intentionally ignored.
    """
    sender = sender or {}
    account_type = str(sender.get("customer_type") or "customer").strip().lower()
    if account_type != "pos":
        raise HTTPException(status_code=403, detail="ليس لديك صلاحية لتنفيذ تحويل لمشترك.")
    return sender

async def _public_transfer_precondition(data: TransferConfirmIn):
    """Authenticate and authorize before idempotency can return any result."""
    return _require_pos_transfer_sender(await _verify_public_customer(data.phone, data.password))

@api.post("/public/card-order/transfer/lookup")
async def public_transfer_lookup(data: TransferLookupIn):
    sender = _require_pos_transfer_sender(await _verify_public_customer(data.phone, data.password))
    if data.amount <= 0: raise HTTPException(status_code=400, detail="المبلغ غير صحيح")
    recipient = await _find_customer_by_phone_or_alternative(data.recipient_phone)
    if not recipient: raise HTTPException(status_code=404, detail="الحساب غير موجود")
    if recipient.get("id") == sender.get("id"): raise HTTPException(status_code=400, detail="لا يمكن التحويل لنفس الحساب")
    financials = _transfer_financials(sender, recipient, data.amount)
    commission = financials["commission"]
    total_debit = financials["sender_debit"]
    # Credit-limit check
    _ensure_customer_credit_limit(sender, total_debit)
    return {
        "sender_id": sender["id"], "sender_type": sender.get("customer_type", "customer"),
        "recipient_id": recipient["id"], "recipient_name": _short_customer_name(recipient.get("name")),
        "recipient_short_name": _short_customer_name(recipient.get("name")),
        "recipient_phone": ("••••" + _phone_last_two(recipient.get("phone"))) if _phone_last_two(recipient.get("phone")) else "",
        "recipient_phone_last2": _phone_last_two(recipient.get("phone")),
        "recipient_alternative_number": recipient.get("alternative_number") or await _ensure_customer_alternative_number(recipient),
        "recipient_type": recipient.get("customer_type","customer"),
        "amount": float(data.amount), "commission": commission,
        "sender_debit": total_debit, "recipient_credit": float(data.amount),
    }

@api.post("/public/card-order/transfer/confirm")
@idempotent_operation("public_transfer", "transfers", precondition=_public_transfer_precondition)
async def public_transfer_confirm(data: TransferConfirmIn):
    if not data.idempotency_key: raise HTTPException(status_code=400, detail="مفتاح الحماية مطلوب")
    sender = _require_pos_transfer_sender(await _verify_public_customer(data.phone, data.password))
    existing = await db.transfers.find_one({"idempotency_key": data.idempotency_key})
    if existing: return clean_doc(existing)
    recipient = await _find_customer_by_phone_or_alternative(data.recipient_phone)
    if not recipient: raise HTTPException(status_code=404, detail="الحساب غير موجود")
    if recipient.get("id") == sender.get("id"): raise HTTPException(status_code=400, detail="لا يمكن التحويل لنفس الحساب")
    if data.amount <= 0: raise HTTPException(status_code=400, detail="المبلغ غير صحيح")
    await _reject_duplicate_financial_operation("customer", sender["id"], data.amount, "تحويل الرصيد", data.allow_duplicate)
    await _reject_duplicate_financial_operation("customer", recipient["id"], data.amount, "تحويل الرصيد", data.allow_duplicate)
    financials = _transfer_financials(sender, recipient, data.amount)
    commission = financials["commission"]
    sender_debit = financials["sender_debit"]
    # Credit-limit final check
    _ensure_customer_credit_limit(sender, sender_debit)
    number = (data.number or "").strip() or await next_gwd_number()
    doc = {
        "id": str(uuid.uuid4()), "number": number, "idempotency_key": data.idempotency_key,
        "sender_id": sender["id"], "sender_name": sender.get("name", ""), "sender_phone": sender.get("phone", ""),
        "sender_type": sender.get("customer_type", "customer"),
        "recipient_id": recipient["id"], "recipient_name": _short_customer_name(recipient.get("name")),
        "recipient_short_name": _short_customer_name(recipient.get("name")),
        "recipient_phone": recipient.get("phone", ""),
        "recipient_alternative_number": recipient.get("alternative_number") or await _ensure_customer_alternative_number(recipient),
        "recipient_type": recipient.get("customer_type", "customer"),
        "amount": float(data.amount), "commission": commission, "sender_debit": sender_debit,
        "description": (data.description or "").strip(), "reference": number,
        "operation_type": "subscriber_transfer", "channel": "public_transfer",
        "status": "active", "created_at": now_iso(), "operation_at": now_iso(),
    }
    transfer_note = (data.description or "").strip()
    sender_ledger_description = f"تحويل صادر إلى {recipient.get('name', '') or 'مشترك'} — المبلغ: {float(data.amount):,.2f}"
    if commission:
        sender_ledger_description += f" — العمولة: {commission:,.2f} — إجمالي الخصم: {sender_debit:,.2f}"
    recipient_ledger_description = f"تحويل وارد من {sender.get('name', '') or 'مشترك'} — المبلغ المستلم: {float(data.amount):,.2f}"
    if transfer_note:
        sender_ledger_description += f" — البيان: {transfer_note}"
        recipient_ledger_description += f" — البيان: {transfer_note}"
    sender_adjusted = False
    recipient_adjusted = False
    try:
        sender_balance_after = await _adjust_party_balance("customer", sender["id"], sender_debit, number, sender_ledger_description)
        sender_adjusted = True
        recipient_balance_after = await _adjust_party_balance("customer", recipient["id"], -float(data.amount), number, recipient_ledger_description)
        recipient_adjusted = True
        doc["sender_balance_after"] = sender_balance_after
        doc["recipient_balance_after"] = recipient_balance_after
        await db.transfers.insert_one(doc)
    except Exception:
        if recipient_adjusted:
            await _remove_ledger_by_op("customer", recipient["id"], number)
        if sender_adjusted:
            await _remove_ledger_by_op("customer", sender["id"], number)
        raise
    try:
        await notify(
            "تحويل لمشترك",
            await _render_message_template("subscriber_transfer_notification", {"amount": float(data.amount), "sender_name": sender.get("name", ""), "recipient_name": recipient.get("name", ""), "number": number}),
            "info",
            details={"operation": "subscriber_transfer", "amount": float(data.amount), "source_name": sender.get("name", ""), "dest_name": recipient.get("name", ""), "number": number, "created_at": doc.get("created_at")},
        )
        incoming_message = (
            f"تم استلام تحويل رصيد بقيمة {float(data.amount):,.2f} "
            f"من {sender.get('name') or sender.get('phone') or 'حساب آخر'} "
            f"— رقم العملية {number}."
        )
        await notify_customer_account(
            recipient["id"],
            "استلام تحويل رصيد",
            incoming_message,
            "success",
            details={
                "operation": "subscriber_transfer",
                "direction": "incoming",
                "amount": float(data.amount),
                "number": number,
                "sender": {
                    "id": sender.get("id"),
                    "name": sender.get("name", ""),
                    "phone": sender.get("phone", ""),
                },
                "recipient": {
                    "id": recipient.get("id"),
                    "name": recipient.get("name", ""),
                    "phone": recipient.get("phone", ""),
                },
                "balance_after": doc.get("recipient_balance_after"),
                "created_at": doc.get("created_at"),
            },
        )
    except Exception as exc:
        logger.warning("subscriber transfer notification failed: %s", exc)
    return _public_transfer_view(doc)


# ================= ADMIN QUICK RECHARGE (from company cash — no commission) =================
class AdminQuickTransferIn(BaseModel):
    recipient_phone: str
    amount: float = Field(gt=0)
    idempotency_key: Optional[str] = None
    allow_duplicate: bool = False
    number: Optional[str] = None

@api.post("/admin/quick-recharge/lookup")
async def admin_quick_recharge_lookup(data: AdminQuickTransferIn, user=Depends(require_perm("receipts"))):
    if data.amount <= 0: raise HTTPException(status_code=400, detail="المبلغ غير صحيح")
    recipient = await _find_customer_by_phone_or_alternative(data.recipient_phone)
    if not recipient: raise HTTPException(status_code=404, detail="حساب المستلم غير موجود")
    category = await get_balance_category()
    stock = await db.stock.find_one({"category_id": category["id"]})
    balance_stock = max(0.0, float((stock or {}).get("total", 0) or 0) - float((stock or {}).get("sold", 0) or 0))
    return {
        "sender_name": "شبكة جواد نت اللاسلكية",
        "source": "cash",
        "recipient_id": recipient["id"], "recipient_name": recipient.get("name", ""),
        "recipient_phone": recipient.get("phone", ""), "recipient_type": recipient.get("customer_type","customer"),
        "recipient_balance": float(recipient.get("balance") or 0),
        "amount": float(data.amount), "commission": 0.0,
        "cash_debit": float(data.amount), "recipient_credit": float(data.amount),
        "balance_stock": balance_stock, "balance_stock_sufficient": balance_stock >= float(data.amount),
    }

@api.post("/admin/quick-recharge/confirm")
@idempotent_operation("quick_recharge", "transfers")
async def admin_quick_recharge_confirm(data: AdminQuickTransferIn, user=Depends(require_perm("receipts"))):
    if not data.idempotency_key: raise HTTPException(status_code=400, detail="مفتاح الحماية مطلوب")
    existing = await db.transfers.find_one({"idempotency_key": data.idempotency_key})
    if existing: return clean_doc(existing)
    if data.amount <= 0: raise HTTPException(status_code=400, detail="المبلغ غير صحيح")
    recipient = await _find_customer_by_phone_or_alternative(data.recipient_phone)
    if not recipient: raise HTTPException(status_code=404, detail="حساب المستلم غير موجود")
    category = await get_balance_category()
    amount = float(data.amount)
    await _reject_duplicate_financial_operation("customer", recipient["id"], amount, "تحويل الرصيد", data.allow_duplicate)
    number = (data.number or "").strip() or await next_gwd_number()
    if await db.transfers.find_one({"number": number}) or await db.receipts.find_one({"number": number}) or await db.stock_ops.find_one({"number": number}):
        raise HTTPException(status_code=409, detail="رقم العملية مستخدم مسبقاً")
    stock = await db.stock.find_one({"category_id": category["id"]})
    available = float((stock or {}).get("total", 0) or 0) - float((stock or {}).get("sold", 0) or 0)
    if available < amount:
        raise HTTPException(status_code=400, detail="رصيد مخزون الرصيد غير كافٍ لإتمام العملية.")
    desc = "بيع رصيد نقدي — تحويل رصيد إلى " + (recipient.get("name") or recipient.get("phone") or "الحساب")
    when = now_iso()
    transfer_id = str(uuid.uuid4())
    stock_op_id = str(uuid.uuid4())
    receipt_id = str(uuid.uuid4())
    balance_after = None
    doc = {
        "id": transfer_id, "number": number, "idempotency_key": data.idempotency_key,
        "source_type": "balance_stock", "source_id": category["id"], "source_name": category.get("name", BALANCE_CATEGORY_NAME),
        "dest_type": "customer", "dest_id": recipient["id"], "dest_name": recipient.get("name", ""), "dest_phone": recipient.get("phone", "") or "",
        "sender_name": category.get("name", BALANCE_CATEGORY_NAME), "recipient_name": recipient.get("name", ""), "recipient_phone": recipient.get("phone", "") or "",
        "party_name": recipient.get("name", ""), "party_id": recipient["id"],
        "amount": amount, "commission": 0.0, "sender_debit": amount, "recipient_credit": amount,
        "description": desc, "operation_type": "quick_recharge", "operation_label": "تحويل رصيد",
        "account_effect": "credit", "account_credit": amount, "cash_effect": "credit", "cash_credit": amount,
        "channel": "admin_quick_recharge", "status": "active", "user_id": user["id"], "username": user.get("username"), "created_at": when, "operation_at": when,
    }
    stock_op = {
        "id": stock_op_id, "number": number, "category_id": category["id"], "category_name": category.get("name", BALANCE_CATEGORY_NAME),
        "kind": "balance_transfer_out", "amount": amount, "quantity": amount, "description": desc,
        "user_id": user["id"], "username": user.get("username"), "created_at": when,
        "balance_before": available, "balance_after": available - amount, "transfer_id": transfer_id,
    }
    receipt = {
        "id": receipt_id, "number": number, "idempotency_key": data.idempotency_key, "type": "receipt_voucher", "kind": "receipt",
        "party_type": "customer", "party_id": recipient["id"], "party_name": recipient.get("name", ""), "amount": amount,
        "description": desc, "operation_type": "quick_recharge", "operation_label": "تحويل رصيد", "channel": "admin_quick_recharge",
        "account_effect": "credit", "account_credit": amount, "cash_effect": "credit", "cash_credit": amount, "commission": 0.0,
        "user_id": user["id"], "username": user.get("username"), "status": "active", "created_at": when, "operation_at": when,
    }
    stock_changed = False
    recipient_adjusted = False
    transfer_inserted = False
    receipt_inserted = False
    try:
        changed = await db.stock.update_one({"category_id": category["id"], "$expr": {"$gte": [{"$subtract": ["$total", {"$ifNull": ["$sold", 0]}]}, amount]}}, {"$inc": {"total": -amount}})
        if changed.modified_count != 1:
            raise HTTPException(status_code=400, detail="رصيد مخزون الرصيد غير كافٍ لإتمام العملية.")
        stock_changed = True
        balance_after = await _adjust_party_balance("customer", recipient["id"], -amount, number, f"تحويل وارد من شبكة جواد نت — {number}")
        recipient_adjusted = True
        transfer_doc = {**doc, "recipient_balance_after": balance_after}
        receipt["balance_after"] = balance_after
        await db.stock_ops.insert_one(stock_op)
        await db.receipts.insert_one(receipt)
        receipt_inserted = True
        await db.transfers.insert_one(transfer_doc)
        transfer_inserted = True
        doc = transfer_doc
    except Exception:
        if transfer_inserted:
            await db.transfers.delete_one({"id": transfer_id})
        if receipt_inserted:
            await db.receipts.delete_one({"id": receipt_id})
        await db.stock_ops.delete_one({"id": stock_op_id})
        if recipient_adjusted:
            await _remove_ledger_by_op("customer", recipient["id"], number)
        if stock_changed:
            await db.stock.update_one({"category_id": category["id"]}, {"$inc": {"total": amount}})
        raise
    try:
        await notify(
            "تحويل رصيد",
            await _render_message_template("quick_recharge_notification", {"amount": float(data.amount), "recipient_name": recipient.get("name", ""), "number": number}),
            "info",
            details={"operation": "quick_recharge", "amount": float(data.amount), "dest_name": recipient.get("name", ""), "number": number, "created_at": doc.get("created_at")},
        )
        _qr_title = "استلام تحويل رصيد"
        _qr_msg = f"تم استلام {amount:,.0f} من شبكة جواد نت اللاسلكية — عملية {number}."
        _qr_id = str(uuid.uuid4())
        await db.notifications.insert_one({
            "id": _qr_id, "title": _qr_title,
            "message": _qr_msg,
            "type": "success", "read": False, "created_at": now_iso(),
            "customer_id": recipient["id"], "kind": "quick_recharge",
        })
        await _notify_push(_qr_id, _qr_title, _qr_msg, "success", {"kind": "quick_recharge", "number": number}, customer_id=recipient["id"])
        await audit_log(user, "create", "quick_recharge", doc["id"], None, {"amount": data.amount, "recipient": recipient.get("phone")})
    except Exception as exc:
        logger.warning("quick recharge post-commit notification/audit failed: %s", exc)
    return clean_doc({**doc, "cash_credit": amount, "account_credit": amount, "commission": 0.0})


# ================= NOTIFICATIONS (admin broadcast + customer read) =================
class BroadcastIn(BaseModel):
    title: str
    message: str
    recipients: Optional[List[str]] = None  # customer ids; None or [] = all customers
    audience: Literal["all", "pos", "customer"] = "all"
    channels: Optional[List[str]] = None    # in_app | sms | whatsapp

@api.post("/notifications/broadcast")
async def broadcast_notification(data: BroadcastIn, user=Depends(require_perm("settings"))):
    if not data.title or not data.message: raise HTTPException(status_code=400, detail="العنوان والنص إلزاميان")
    channels = [c for c in (data.channels or ["in_app"]) if c in ("in_app", "sms", "whatsapp")]
    if not channels:
        channels = ["in_app"]
    notification_settings, messaging_settings = await _app_channel_settings()
    in_app_enabled = bool("in_app" in channels and notification_settings.get("enabled", True) and notification_settings.get("in_app_enabled", True))
    outreach_channels = []
    for channel in ("sms", "whatsapp"):
        if channel not in channels:
            continue
        if channel == "sms" and messaging_settings.get("sms_enabled", True):
            outreach_channels.append(channel)
        if channel == "whatsapp" and messaging_settings.get("whatsapp_enabled", True):
            outreach_channels.append(channel)
    if not in_app_enabled and not outreach_channels:
        return {"ok": True, "count": 0, "disabled": True, "channels": channels}
    if data.recipients:
        ids = data.recipients
    else:
        audience_query: Dict[str, Any] = {"status": {"$ne": "disabled"}}
        # Historical records use customer_type, while some imported accounts
        # use account_type/type and upper-case values. Build the audience from
        # the database record, never from a client-supplied account_type.
        pos_markers = [
            {"customer_type": {"$regex": "^pos$", "$options": "i"}},
            {"account_type": {"$regex": "^pos$", "$options": "i"}},
            {"type": {"$regex": "^pos$", "$options": "i"}},
        ]
        if data.audience == "pos":
            audience_query["$or"] = pos_markers
        elif data.audience == "customer":
            audience_query["$nor"] = pos_markers
        customers = await db.customers.find(audience_query, {"id": 1}).to_list(10000)
        ids = [c["id"] for c in customers]
    now = now_iso()
    group_id = str(uuid.uuid4())
    docs = []
    if in_app_enabled:
        docs = [{
            "id": str(uuid.uuid4()), "group_id": group_id,
            "title": data.title, "message": data.message,
            "type": "info", "read": False, "created_at": now,
            "customer_id": cid, "kind": "admin_broadcast",
            "sender_username": user.get("username"),
            "channels": channels,
        } for cid in ids]
        if docs: await db.notifications.insert_many(docs)
    from urllib.parse import quote as _quote
    outreach: List[Dict[str, Any]] = []
    if outreach_channels and ids:
        people = await db.customers.find({"id": {"$in": ids}}, {"id": 1, "name": 1, "phone": 1}).to_list(10000)
        for person in people:
            phone = _clean_phone(person.get("phone"))
            text = data.message.strip()
            outreach.append({
                "customer_id": person.get("id"),
                "name": person.get("name") or "",
                "phone": phone,
                "whatsapp_url": f"https://wa.me/{phone.lstrip('+')}?text={_quote(text)}" if ("whatsapp" in outreach_channels and phone) else "",
                "sms_phone": phone if ("sms" in outreach_channels and phone) else "",
                "sms_text": text if ("sms" in outreach_channels and phone) else "",
            })
    await db.broadcast_logs.insert_one({
        "id": str(uuid.uuid4()), "group_id": group_id,
        "title": data.title, "message": data.message,
        "audience": data.audience, "channels": channels,
        "count": len(ids), "outreach_count": len(outreach),
        "sender_username": user.get("username"), "created_at": now,
    })
    # Persisted inbox entries are kept as the source of truth. When VAPID is
    # configured, also fan out a background push per selected account so a
    # subscribed web client can receive it while closed. Android APK delivery
    # still requires an FCM bridge; this does not pretend Web Push is FCM.
    if in_app_enabled and ids:
        _bc_title = data.title.strip()[:120]
        _bc_body = data.message.strip()[:500]
        for cid in ids:
            if _webpush is not None and os.getenv("VAPID_PRIVATE_KEY") and os.getenv("VAPID_PUBLIC_KEY"):
                asyncio.create_task(_send_web_push(_bc_title, _bc_body, "info", user_id=cid))
            # إشعار فوري لأي جهاز أندرويد مسجَّل على هذا الحساب (حتى والتطبيق مغلق)
            asyncio.create_task(_send_fcm(_bc_title, _bc_body, "info", cid,
                                          {"kind": "admin_broadcast", "notification_id": group_id, "group_id": group_id}, True))
    return {"ok": True, "count": len(docs) if in_app_enabled else len(ids), "group_id": group_id,
            "channels": channels, "in_app": in_app_enabled,
            "outreach": outreach[:300], "outreach_total": len(outreach)}

@api.get("/notifications/broadcast-log")
async def broadcast_log(user=Depends(require_perm("settings"))):
    rows = await db.notifications.aggregate([
        {"$match": {"kind": "admin_broadcast"}},
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$group_id", "title": {"$first": "$title"}, "message": {"$first": "$message"},
                    "created_at": {"$first": "$created_at"}, "sender_username": {"$first": "$sender_username"},
                    "count": {"$sum": 1}, "read_count": {"$sum": {"$cond": ["$read", 1, 0]}},
                    "channels": {"$first": "$channels"}}},
        {"$sort": {"created_at": -1}}, {"$limit": 200}
    ]).to_list(200)
    seen = {str(row.get("_id")) for row in rows}
    extra = await db.broadcast_logs.find({"group_id": {"$nin": list(seen)}}).sort("created_at", -1).limit(100).to_list(100)
    for row in extra:
        rows.append({
            "_id": row.get("group_id"),
            "title": row.get("title"),
            "message": row.get("message"),
            "created_at": row.get("created_at"),
            "sender_username": row.get("sender_username"),
            "count": row.get("count", 0),
            "read_count": 0,
            "channels": row.get("channels", []),
        })
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows

class BroadcastDeleteManyIn(BaseModel):
    group_ids: List[str] = Field(default_factory=list, max_length=200)

@api.post("/notifications/broadcast/delete")
async def delete_broadcast(group_id: str, user=Depends(require_perm("settings"))):
    group_id = (group_id or "").strip()
    if not group_id:
        raise HTTPException(status_code=400, detail="معرّف الإشعار مطلوب")
    result = await db.notifications.delete_many({"kind": "admin_broadcast", "group_id": group_id})
    await db.broadcast_logs.delete_many({"group_id": group_id})
    return {"ok": True, "deleted": result.deleted_count, "group_id": group_id}

@api.post("/notifications/broadcast/delete-many")
async def delete_broadcast_many(data: BroadcastDeleteManyIn, user=Depends(require_perm("settings"))):
    ids = list(dict.fromkeys((gid or "").strip() for gid in data.group_ids if (gid or "").strip()))
    if not ids:
        raise HTTPException(status_code=400, detail="اختر إشعاراً واحداً على الأقل")
    result = await db.notifications.delete_many({"kind": "admin_broadcast", "group_id": {"$in": ids}})
    await db.broadcast_logs.delete_many({"group_id": {"$in": ids}})
    return {"ok": True, "deleted": result.deleted_count, "groups": len(ids)}

class PublicNotifIn(BaseModel):
    phone: str
    password: str

@api.post("/public/card-order/notifications")
async def public_notifications(data: PublicNotifIn):
    c = await _verify_public_customer(data.phone, data.password)
    items = await db.notifications.find({"customer_id": c["id"]}).sort("created_at", -1).limit(200).to_list(200)
    unread = await db.notifications.count_documents({"customer_id": c["id"], "read": False})
    return {"items": [clean_doc(x) for x in items], "unread": unread}

class PublicNotifReadIn(PublicNotifIn):
    notif_id: str

class PublicPushSubscribeIn(BaseModel):
    phone: str
    password: str
    subscription: Dict[str, Any]


@api.post("/public/card-order/push-subscribe")
async def public_push_subscribe(data: PublicPushSubscribeIn):
    customer = await _verify_public_customer(data.phone, data.password)
    sub = data.subscription or {}
    endpoint = sub.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="اشتراك الإشعارات غير صالح")
    await db.push_subscriptions.update_one(
        {"endpoint": endpoint},
        {"$set": {"id": str(uuid.uuid4()), "endpoint": endpoint, "subscription": sub, "user_id": customer["id"], "customer_id": customer["id"], "role": "customer", "updated_at": now_iso()}, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True}


class PublicPopupSeenIn(PublicNotifIn):
    notif_ids: List[str]
@api.post("/public/card-order/notifications/popup-seen")
async def public_popup_seen(data: PublicPopupSeenIn):
    """تعليم إشعارات «وصلك كرت» كمُعرَضة في النافذة المنبثقة حتى لا تتكرر."""
    c = await _verify_public_customer(data.phone, data.password)
    ids = [str(i) for i in (data.notif_ids or [])][:50]
    if ids:
        await db.notifications.update_many(
            {"customer_id": c["id"], "id": {"$in": ids}},
            {"$set": {"details.popup_seen": True, "popup_seen_at": now_iso()}},
        )
    return {"ok": True}
@api.post("/public/card-order/notifications/mark-read")
async def public_notif_mark_read(data: PublicNotifReadIn):
    c = await _verify_public_customer(data.phone, data.password)
    await db.notifications.update_one({"id": data.notif_id, "customer_id": c["id"]}, {"$set": {"read": True, "read_at": now_iso()}})
    return {"ok": True}


# ================= INCENTIVES =================
async def _get_incentive_settings():
    doc = await db.settings.find_one({"_key": "incentives"}) or {}
    return {
        "customer_enabled": bool(doc.get("customer_enabled", False)),
        "pos_enabled": bool(doc.get("pos_enabled", False)),
        "exclude_special_price": bool(doc.get("exclude_special_price", False)),
    }

async def _apply_incentive_on_sale(sale_doc: dict, customer: Optional[dict]):
    """Deprecated: pending earnings are now computed dynamically from cumulative sales.
    Kept as a no-op to avoid changing the create_sale call site."""
    return

async def _sum_bought_by_category(customer_id: str) -> Dict[str, int]:
    """Sum quantity per category from all active sales of this customer."""
    pipeline = [
        {"$match": {"customer_id": customer_id, "status": {"$ne": "cancelled"}}},
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.category_id", "qty": {"$sum": "$items.quantity"}}}
    ]
    out: Dict[str, int] = {}
    async for row in db.sales.aggregate(pipeline):
        out[row["_id"]] = int(row.get("qty") or 0)
    return out

async def _customer_incentive_summary(customer: dict) -> Dict[str, Any]:
    """Cumulative per-category incentive state for one customer.
    Returns categories with rule + bought + earned + redeemed + pending + status text."""
    settings = await _get_incentive_settings()
    ctype = customer.get("customer_type", "customer")
    enabled = settings["pos_enabled"] if ctype == "pos" else settings["customer_enabled"]
    if settings.get("exclude_special_price") and customer.get("special_prices_enabled"):
        enabled = False
    if customer.get("incentives_visible") is False:
        enabled = False
    rules = await db.incentive_rules.find({"account_type": ctype, "active": True}).to_list(500)
    if not enabled or not rules:
        return {"enabled": bool(enabled), "categories": [], "history": []}
    bought_map = await _sum_bought_by_category(customer["id"])
    result = []
    # Cumulative buys minus baseline (baseline set on each incentive card-redemption)
    baseline_map: Dict[str, int] = {}
    for b in (customer.get("incentive_baseline") or []):
        cid_key = b.get("category_id"); qval = int(b.get("bought_at_redeem") or 0)
        if cid_key: baseline_map[cid_key] = qval
    for r in rules:
        cid = r.get("category_id"); buy = int(r.get("buy_qty") or 0); reward = int(r.get("reward_qty") or 0)
        if not cid or buy <= 0 or reward <= 0: continue
        cat = await db.card_categories.find_one({"id": cid}) or {}
        raw_bought = int(bought_map.get(cid, 0))
        baseline = int(baseline_map.get(cid, 0))
        bought = max(0, raw_bought - baseline)
        # earnings from THIS cycle only
        total_earned_ever = (bought // buy) * reward
        red_docs = await db.incentive_earnings.find({
            "customer_id": customer["id"], "category_id": cid,
            "status": {"$in": ["redeemed_card", "redeemed_credit"]},
            "cycle_start_bought": {"$gte": baseline},
        }).to_list(1000)
        redeemed_qty = sum(int(x.get("qty") or 0) for x in red_docs)
        pending_qty = max(0, total_earned_ever - redeemed_qty)
        used_towards_earned = (total_earned_ever // reward) * buy if reward else 0
        remaining_for_next = max(0, buy - (bought - used_towards_earned))
        if pending_qty > 0:
            status_text = f"حافز مستحق ({pending_qty} كرت)" + (f" — متبقي {remaining_for_next} للحافز القادم" if remaining_for_next < buy else "")
        elif bought == 0:
            status_text = f"لم يبدأ الشراء من هذه الفئة"
        else:
            status_text = f"تبقى {remaining_for_next} كرت للحصول على الحافز"
        result.append({
            "rule_id": r.get("id"),
            "category_id": cid,
            "category_name": cat.get("name", ""),
            "unit_value": cat.get("sale_price_customer") or cat.get("sale_price", 0),
            "bought": bought,
            "buy_qty": buy,
            "reward_qty": reward,
            "earned_total": total_earned_ever,
            "redeemed": redeemed_qty,
            "pending_qty": pending_qty,
            "remaining_for_next": remaining_for_next,
            "status_text": status_text,
        })
    # history (redeemed only)
    history = await db.incentive_earnings.find({
        "customer_id": customer["id"],
        "status": {"$in": ["redeemed_card", "redeemed_credit"]}
    }).sort("redeemed_at", -1).limit(200).to_list(200)
    return {"enabled": True, "categories": result, "history": [clean_doc(h) for h in history]}


class PublicAuth(BaseModel):
    phone: str
    password: str

class PublicFavoriteItem(BaseModel):
    phone: str
    name: Optional[str] = ""

class PublicFavoritesReplaceIn(PublicAuth):
    items: List[PublicFavoriteItem] = Field(default_factory=list, max_length=200)

class IncentiveRedeemIn(PublicAuth):
    mode: str  # "card" | "credit"
    category_id: Optional[str] = None
    qty: Optional[int] = None  # partial redeem; defaults to all pending

async def _verify_public_customer(phone: str, password: str):
    c = await db.customers.find_one({"phone": phone})
    if not c or c.get("password") != password:
        raise HTTPException(status_code=401, detail="بيانات غير صحيحة")
    if c.get("status") == "disabled":
        raise HTTPException(status_code=403, detail="الحساب معطل")
    return c

def _clean_public_favorite(item: PublicFavoriteItem) -> dict:
    digits = _re.sub(r"\D", "", str(item.phone or ""))
    if _valid_alternative_number(digits):
        return {"phone": digits, "name": (str(item.name or "").strip() or digits)[:120]}
    if digits.startswith("967"):
        digits = digits[3:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if not _re.fullmatch(r"(?:7|9)\d{8}", digits):
        raise HTTPException(status_code=400, detail="رقم المفضلة يجب أن يكون رقم جوال يمني صحيحاً")
    return {"phone": digits, "name": (str(item.name or "").strip() or digits)[:120]}

@api.get("/public/card-order/favorites")
async def public_favorites_list(phone: str, password: str):
    customer = await _verify_public_customer(phone, password)
    return {
        "items": customer.get("portal_favorites", []) or [],
        "customer_id": customer["id"],
        "initialized": bool(customer.get("portal_favorites_initialized", False)),
    }

@api.post("/public/card-order/favorites")
async def public_favorites(data: PublicFavoritesReplaceIn):
    customer = await _verify_public_customer(data.phone, data.password)
    items = []
    seen = set()
    for item in data.items:
        clean = _clean_public_favorite(item)
        if clean["phone"] not in seen:
            items.append(clean)
            seen.add(clean["phone"])
    await db.customers.update_one(
        {"id": customer["id"]},
        {"$set": {
            "portal_favorites": items,
            "portal_favorites_initialized": True,
            "portal_favorites_updated_at": now_iso(),
        }},
    )
    return {"items": items, "customer_id": customer["id"], "initialized": True}

async def _redeem_incentive(customer: dict, category_id: str, mode: str, qty_req: Optional[int], acting_user: Optional[dict]):
    summary = await _customer_incentive_summary(customer)
    row = next((x for x in summary["categories"] if x["category_id"] == category_id), None)
    if not row or row["pending_qty"] <= 0:
        raise HTTPException(status_code=400, detail="لا يوجد حافز مستحق لهذه الفئة")
    qty = int(qty_req or row["pending_qty"])
    if qty <= 0 or qty > row["pending_qty"]:
        raise HTTPException(status_code=400, detail="الكمية المطلوبة غير صحيحة")
    now = now_iso()
    rec_id = str(uuid.uuid4())
    base_rec = {
        "id": rec_id,
        "customer_id": customer["id"],
        "customer_name": customer.get("name", ""),
        "customer_type": customer.get("customer_type", "customer"),
        "category_id": category_id,
        "category_name": row["category_name"],
        "unit_value": row["unit_value"],
        "qty": qty,
        "buy_qty": row["buy_qty"],
        "reward_qty": row["reward_qty"],
        "created_at": now,
        "redeemed_at": now,
        "redeemed_by": (acting_user or {}).get("username", "public"),
    }
    base_rec["cycle_start_bought"] = 0  # not used for credit
    if mode == "credit":
        value = float(row["unit_value"] or 0) * qty
        await _adjust_party_balance("customer", customer["id"], -value, f"INC-{rec_id[:8]}", f"حافز {row['category_name']} × {qty}")
        base_rec.update({"status": "redeemed_credit", "redeemed_value": value})
        await db.incentive_earnings.insert_one(base_rec)
        return {"ok": True, "mode": "credit", "value": value}
    # cards
    avail_num = await db.cards.count_documents({"category_id": category_id, "status": "available"})
    stock = await db.stock.find_one({"category_id": category_id})
    avail_qty = (stock or {}).get("total", 0) - (stock or {}).get("sold", 0) if stock else 0
    if avail_num + avail_qty < qty:
        raise HTTPException(status_code=400, detail="لا يوجد رصيد كافٍ من الكروت لتسليم الحافز")
    take_num = min(qty, avail_num)
    cards_delivered = []
    if take_num > 0:
        picks = await db.cards.find({"category_id": category_id, "status": "available"}).limit(take_num).to_list(take_num)
        ids = [x["id"] for x in picks]
        cards_delivered = [x["number"] for x in picks]
        await db.cards.update_many({"id": {"$in": ids}}, {"$set": {"status": "sold", "sold_at": now, "sold_to": customer["id"]}})
    take_qty = qty - take_num
    if take_qty > 0:
        await db.stock.update_one({"category_id": category_id}, {"$inc": {"sold": take_qty}})
    base_rec.update({"status": "redeemed_card", "cards": cards_delivered})
    await db.incentive_earnings.insert_one(base_rec)
    # Reset baseline for this category so the display counter starts from 0
    raw = await _sum_bought_by_category(customer["id"])
    new_baseline = int(raw.get(category_id, 0))
    existing = [b for b in (customer.get("incentive_baseline") or []) if b.get("category_id") != category_id]
    existing.append({"category_id": category_id, "bought_at_redeem": new_baseline, "reset_at": now})
    await db.customers.update_one({"id": customer["id"]}, {"$set": {"incentive_baseline": existing}})
    # Create a notification the customer can see
    _inc_title = "استلام حافز"
    _inc_msg = f"تم استلام {qty} كرت من فئة {row['category_name']} كحافز."
    _inc_id = str(uuid.uuid4())
    await db.notifications.insert_one({
        "id": _inc_id, "title": _inc_title,
        "message": _inc_msg,
        "type": "success", "read": False, "created_at": now,
        "customer_id": customer["id"], "kind": "incentive",
    })
    await _notify_push(_inc_id, _inc_title, _inc_msg, "success", {"kind": "incentive"}, customer_id=customer["id"])
    return {"ok": True, "mode": "card", "cards": cards_delivered, "qty": qty}


@api.get("/customers/{cid}/incentives")
async def admin_customer_incentives(cid: str, user=Depends(require_perm("customers"))):
    c = await db.customers.find_one({"id": cid})
    if not c: raise HTTPException(status_code=404, detail="غير موجود")
    return await _customer_incentive_summary(c)

@api.post("/customers/{cid}/incentives/redeem")
@serialized_financial_operation
async def admin_redeem_customer_incentive(cid: str, category_id: str, mode: str, qty: Optional[int] = None, user=Depends(require_perm("sales"))):
    c = await db.customers.find_one({"id": cid})
    if not c: raise HTTPException(status_code=404, detail="غير موجود")
    if mode not in ("card","credit"): raise HTTPException(status_code=400, detail="نوع الصرف غير صالح")
    return await _redeem_incentive(c, category_id, mode, qty, user)

@api.post("/public/card-order/incentives")
async def public_list_incentives(data: PublicAuth):
    c = await _verify_public_customer(data.phone, data.password)
    return await _customer_incentive_summary(c)

@api.post("/public/card-order/incentives/redeem")
@serialized_financial_operation
async def public_redeem_incentive(data: IncentiveRedeemIn):
    if not data.category_id or data.mode not in ("card","credit"):
        raise HTTPException(status_code=400, detail="بيانات غير صحيحة")
    c = await _verify_public_customer(data.phone, data.password)
    return await _redeem_incentive(c, data.category_id, data.mode, data.qty, None)

# Public banks (safe subset for card-order screen)
@api.get("/public/card-order/banks")
async def public_banks(show_in: str = "over_limit"):
    if show_in not in ("portal", "invoices", "receipts", "payment_requests", "over_limit"):
        raise HTTPException(status_code=400, detail="مكان غير صالح")
    items = await db.bank_accounts.find({"active": True, "show_in": show_in}).sort("created_at", 1).to_list(50)
    result = []
    for bank in items:
        result.append({
            "id": bank.get("id"),
            "bank_name": bank.get("bank_name"),
            "provider_type": bank.get("provider_type") or "bank",
            "holder_name": bank.get("holder_name"),
            "account_number": bank.get("account_number"),
            "details": bank.get("details") or "",
            "payment_steps": _bank_payment_steps(bank),
            "minimum_deposit_amount": float(bank.get("minimum_deposit_amount", 250) or 0),
            "payment_theme": _bank_payment_theme(bank),
        })
    return result


@api.get("/public/card-order/customer-qr/{alternative_number}")
async def public_customer_qr(alternative_number: str):
    """Return a QR that contains only the validated six-digit alternative number."""
    raw = str(alternative_number or "").strip()
    if not _valid_alternative_number(raw):
        raise HTTPException(status_code=400, detail="الرقم البديل غير صالح")
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(f"gawad:customer:{raw}")
    qr.make(fit=True)
    image = qr.make_image(fill_color="#221340", back_color="white")
    payload = BytesIO()
    image.save(payload, format="PNG", optimize=True)
    return Response(content=payload.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})

@api.get("/public/card-order/banks/{bank_id}/instruction-image")
async def public_bank_instruction_image(bank_id: str, size: str = "display"):
    raise HTTPException(status_code=410, detail="صور تعليمات السداد غير مدعومة.")
    """Serve only the payment-instruction image of an active portal-visible account."""
    bank = await db.bank_accounts.find_one({"id": bank_id, "active": True})
    if not bank or not _bank_visible_in(bank, "portal"):
        raise HTTPException(status_code=404, detail="صورة تعليمات السداد غير متاحة")
    if size not in ("display", "thumbnail"):
        raise HTTPException(status_code=400, detail="حجم الصورة غير صالح")
    if bank.get("instruction_image_file_id"):
        bank = await _ensure_instruction_image_variants(bank)
    file_id = str(
        (bank.get("instruction_image_thumbnail_file_id") or bank.get("instruction_image_file_id"))
        if size == "thumbnail"
        else (bank.get("instruction_image_display_file_id") or bank.get("instruction_image_file_id"))
    ).strip()
    if not file_id:
        raise HTTPException(status_code=404, detail="لا توجد صورة تعليمات سداد")
    record = await db.files.find_one({"id": file_id, "is_deleted": False})
    if not record or not str(record.get("content_type") or "").lower().startswith("image/"):
        raise HTTPException(status_code=404, detail="صورة تعليمات السداد غير موجودة")
    data, content_type = _get_object(record["storage_path"])
    headers = {
        "Content-Disposition": f'inline; filename="{record.get("original_filename", "payment-instructions-image")}"',
        "Cache-Control": "public, max-age=31536000, immutable" if record.get("variant") else "public, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(
        content=data,
        media_type=record.get("content_type") or content_type,
        headers=headers,
    )


class IncentiveRuleIn(BaseModel):
    account_type: str  # customer / pos
    category_id: str
    buy_qty: int
    reward_qty: int
    active: Optional[bool] = True

class IncentiveSettingsIn(BaseModel):
    customer_enabled: Optional[bool] = False
    pos_enabled: Optional[bool] = False
    exclude_special_price: Optional[bool] = False

@api.get("/incentive-settings")
async def get_incentive_settings(user=Depends(get_current_user)):
    return await _get_incentive_settings()

@api.put("/incentive-settings")
async def set_incentive_settings(data: IncentiveSettingsIn, user=Depends(require_perm("settings"))):
    payload = data.model_dump()
    payload["_key"] = "incentives"
    await db.settings.update_one({"_key": "incentives"}, {"$set": payload}, upsert=True)
    return await _get_incentive_settings()

@api.get("/incentive-rules")
async def list_incentive_rules(user=Depends(get_current_user)):
    items = await db.incentive_rules.find().sort("created_at", -1).to_list(500)
    return [clean_doc(r) for r in items]

@api.post("/incentive-rules")
async def create_incentive_rule(data: IncentiveRuleIn, user=Depends(require_perm("settings"))):
    if data.account_type not in ("customer", "pos"):
        raise HTTPException(status_code=400, detail="نوع الحساب غير صالح")
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = now_iso()
    await db.incentive_rules.insert_one(doc)
    return clean_doc(doc)

@api.put("/incentive-rules/{rid}")
async def update_incentive_rule(rid: str, data: IncentiveRuleIn, user=Depends(require_perm("settings"))):
    r = await db.incentive_rules.update_one({"id": rid}, {"$set": data.model_dump()})
    if r.matched_count == 0: raise HTTPException(status_code=404, detail="غير موجود")
    doc = await db.incentive_rules.find_one({"id": rid})
    return clean_doc(doc)

@api.delete("/incentive-rules/{rid}")
async def delete_incentive_rule(rid: str, user=Depends(require_perm("settings"))):
    await db.incentive_rules.delete_one({"id": rid})
    return {"ok": True}


@api.get("/reports/incentives")
async def incentive_report(start: Optional[str] = None, end: Optional[str] = None,
                            customer_id: Optional[str] = None, category_id: Optional[str] = None,
                            status_filter: Optional[str] = None, kind: Optional[str] = "redeemed",
                            user=Depends(require_perm("reports"))):
    """kind = redeemed | pending"""
    if kind == "pending":
        customers = await db.customers.find({"status": {"$ne": "disabled"}}).to_list(5000)
        if customer_id:
            customers = [c for c in customers if c.get("id") == customer_id]
        rows = []
        total_qty = 0
        total_value = 0.0
        for c in customers:
            summary = await _customer_incentive_summary(c)
            for row in summary.get("categories", []):
                if row.get("pending_qty", 0) <= 0: continue
                if category_id and row.get("category_id") != category_id: continue
                rec = {
                    "id": f"{c.get('id')}::{row.get('category_id')}",
                    "customer_id": c.get("id"),
                    "customer_name": c.get("name", ""),
                    "customer_type": c.get("customer_type", "customer"),
                    "category_id": row.get("category_id"),
                    "category_name": row.get("category_name"),
                    "qty": row.get("pending_qty"),
                    "bought": row.get("bought"),
                    "buy_qty": row.get("buy_qty"),
                    "reward_qty": row.get("reward_qty"),
                    "unit_value": row.get("unit_value"),
                    "redeemed_value": float(row.get("unit_value") or 0) * int(row.get("pending_qty") or 0),
                    "status": "pending",
                    "status_text": row.get("status_text"),
                    "redeemed_by": None,
                    "redeemed_at": None,
                }
                rows.append(rec)
                total_qty += int(row.get("pending_qty") or 0)
                total_value += rec["redeemed_value"]
        return {"items": rows, "total_qty": total_qty, "total_value": total_value, "count": len(rows), "kind": "pending"}

    q: Dict[str, Any] = {"status": {"$in": ["redeemed_card", "redeemed_credit"]}}
    if customer_id: q["customer_id"] = customer_id
    if category_id: q["category_id"] = category_id
    if status_filter: q["status"] = status_filter
    if start or end:
        q["$expr"] = mongo_business_date_expr(start, end, "redeemed_at")
    items = await db.incentive_earnings.find(q).sort("redeemed_at", -1).limit(5000).to_list(5000)
    total_qty = sum(int(x.get("qty") or 0) for x in items)
    total_value = sum(float(x.get("redeemed_value") or (x.get("unit_value") or 0) * (x.get("qty") or 0)) for x in items)
    return {"items": [clean_doc(x) for x in items], "total_qty": total_qty, "total_value": total_value, "count": len(items), "kind": "redeemed"}


@api.post("/sales")
@idempotent_operation("sale", "sales")
async def create_sale(data: SaleIn, user=Depends(require_perm("sales"))):
    if data.idempotency_key:
        existing = await db.sales.find_one({"idempotency_key": data.idempotency_key})
        if existing:
            return clean_doc(existing)
    if not data.customer_id:
        raise HTTPException(status_code=400, detail="يرجى اختيار العميل قبل حفظ الفاتورة.")
    if data.sale_type not in ("cash", "credit"):
        raise HTTPException(status_code=400, detail="يرجى اختيار نوع الفاتورة: نقد أو آجل.")
    if not data.items:
        raise HTTPException(status_code=400, detail="يجب إضافة بند واحد على الأقل إلى الفاتورة.")

    customer = await db.customers.find_one({"id": data.customer_id})
    if not customer:
        raise HTTPException(status_code=404, detail="حساب العميل غير موجود.")

    items_final = []
    customer_type = customer.get("customer_type", "customer")
    special_enabled = bool(customer.get("special_prices_enabled"))
    special_prices = {
        row.get("category_id"): _numeric_amount(row.get("price"), 0.0)
        for row in (customer.get("special_prices") or [])
        if row.get("category_id") and row.get("price") is not None
    }
    for item in data.items:
        category = await db.card_categories.find_one({"id": item.category_id})
        if not category:
            raise HTTPException(status_code=404, detail=f"فئة المخزون غير موجودة: {item.category_name or item.category_id}")
        if is_balance_category(category):
            raise HTTPException(status_code=400, detail="فئة رصيد مخصصة لتحويل الرصيد ولا يمكن بيعها")
        price = float(item.price or 0)
        if price <= 0:
            if special_enabled and item.category_id in special_prices:
                price = special_prices[item.category_id]
            else:
                price = category.get("sale_price_pos") if customer_type == "pos" else category.get("sale_price_customer")
                if price is None:
                    price = category.get("sale_price", 0)
                price = _numeric_amount(price, 0.0)
        if price < 0:
            raise HTTPException(status_code=400, detail="سعر البيع لا يمكن أن يكون سالباً.")
        row = item.model_dump()
        row["price"] = price
        row["total"] = int(item.quantity) * price
        items_final.append(row)

    subtotal = sum(float(item["total"]) for item in items_final)
    discount = float(data.discount or 0)
    if discount < 0 or discount > subtotal:
        raise HTTPException(status_code=400, detail="الخصم لا يمكن أن يكون سالباً أو أكبر من إجمالي الفاتورة.")
    total = subtotal - discount
    raw_paid = float(data.paid or 0)
    if data.sale_type == "credit" and (raw_paid < 0 or raw_paid > total):
        raise HTTPException(status_code=400, detail="المبلغ المدفوع يجب أن يكون بين صفر وإجمالي الفاتورة.")
    paid = total if data.sale_type == "cash" else raw_paid
    remaining = 0.0 if data.sale_type == "cash" else total - paid
    await _reject_duplicate_financial_operation("customer", data.customer_id, total, "فاتورة المبيعات", data.allow_duplicate)
    if data.sale_type == "credit" and remaining > 0:
        _ensure_customer_credit_limit(
            customer,
            remaining,
            f"لا يمكن تنفيذ العملية لأنها تتجاوز سقف حساب العميل ({_customer_credit_limit(customer)})",
        )

    await _validate_sale_inventory(data.items)
    number = (data.number or "").strip() or await next_gwd_number()
    doc = {
        "id": str(uuid.uuid4()), "number": number, "type": "sale",
        "customer_id": data.customer_id, "customer_name": customer.get("name") or data.customer_name,
        "sale_type": data.sale_type, "items": items_final,
        "subtotal": subtotal, "discount": discount, "total": total,
        "paid": paid, "remaining": remaining, "notes": data.notes,
        "user_id": user["id"], "username": user.get("username"), "status": "active",
        "idempotency_key": data.idempotency_key, "local_id": data.local_id,
        "device_id": data.device_id, "created_at": now_iso(), "operation_at": now_iso(),
    }

    stock_changes = []
    sold_card_ids = []
    sale_inserted = False
    try:
        for item in data.items:
            if item.use_numbered and item.card_numbers:
                numbers = [(number or "").strip() for number in item.card_numbers if (number or "").strip()]
                cards = await db.cards.find({"number": {"$in": numbers}, "status": "available"}).to_list(len(numbers))
                if len(cards) != len(numbers):
                    raise HTTPException(status_code=409, detail="تغير توفر أحد الكروت أثناء الحفظ؛ لم تُحفظ الفاتورة.")
                ids = [card["id"] for card in cards]
                result = await db.cards.update_many(
                    {"id": {"$in": ids}, "status": "available"},
                    {"$set": {"status": "sold", "sold_at": now_iso(), "sold_to": data.customer_id}},
                )
                if result.modified_count != len(ids):
                    raise HTTPException(status_code=409, detail="تعارض مخزون أثناء الحفظ؛ لم تُحفظ الفاتورة.")
                sold_card_ids.extend(ids)
            else:
                stock = await db.stock.find_one({"category_id": item.category_id})
                available_quantity = max(int((stock or {}).get("total", 0)) - int((stock or {}).get("sold", 0)), 0)
                take_quantity = min(int(item.quantity), available_quantity)
                if take_quantity:
                    await db.stock.update_one({"category_id": item.category_id}, {"$inc": {"sold": take_quantity}})
                    stock_changes.append((item.category_id, take_quantity))
                remaining_numbered = int(item.quantity) - take_quantity
                if remaining_numbered:
                    cards = await db.cards.find({"category_id": item.category_id, "status": "available"}).limit(remaining_numbered).to_list(remaining_numbered)
                    if len(cards) != remaining_numbered:
                        raise HTTPException(status_code=409, detail="تغير توفر المخزون أثناء الحفظ؛ لم تُحفظ الفاتورة.")
                    ids = [card["id"] for card in cards]
                    result = await db.cards.update_many(
                        {"id": {"$in": ids}, "status": "available"},
                        {"$set": {"status": "sold", "sold_at": now_iso(), "sold_to": data.customer_id}},
                    )
                    if result.modified_count != len(ids):
                        raise HTTPException(status_code=409, detail="تعارض مخزون أثناء الحفظ؛ لم تُحفظ الفاتورة.")
                    sold_card_ids.extend(ids)

        await db.sales.insert_one(doc)
        sale_inserted = True
        if sold_card_ids:
            try:
                _sold_rows = await db.cards.find({"id": {"$in": sold_card_ids}}, {"id": 1, "number": 1}).to_list(len(sold_card_ids))
                await log_card_events(_sold_rows, "sold", user.get("username"),
                                      {"sale_id": doc.get("id"), "sale_number": number,
                                       "customer_id": data.customer_id,
                                       "customer_name": customer.get("name") or ""},
                                      f"فاتورة مبيعات {number}")
            except Exception as exc:
                logger.warning("card sale event log failed: %s", exc)
        balance_after = float(customer.get("balance", 0) or 0)
        if data.sale_type == "credit" and remaining > 0:
            balance_after = await _adjust_party_balance("customer", data.customer_id, remaining, number, f"فاتورة مبيعات {number}")
    except Exception:
        await _remove_ledger_by_op("customer", data.customer_id, number)
        if sale_inserted:
            await db.sales.delete_one({"id": doc["id"]})
        if sold_card_ids:
            await db.cards.update_many(
                {"id": {"$in": sold_card_ids}, "sold_to": data.customer_id},
                {"$set": {"status": "available"}, "$unset": {"sold_at": "", "sold_to": ""}},
            )
            try:
                _rev_rows = await db.cards.find({"id": {"$in": sold_card_ids}}, {"id": 1, "number": 1}).to_list(len(sold_card_ids))
                await log_card_events(_rev_rows, "reverted", user.get("username"),
                                      {"sale_number": number}, f"تعذر حفظ الفاتورة {number} فعاد الكرت متوفراً")
            except Exception as exc:
                logger.warning("card revert event log failed: %s", exc)
        for category_id, quantity in stock_changes:
            await db.stock.update_one({"category_id": category_id}, {"$inc": {"sold": -quantity}})
        raise

    try:
        await _apply_incentive_on_sale(doc, customer)
    except Exception as exc:
        logger.warning("incentive apply failed: %s", exc)
    try:
        await audit_log(user, "create", "sale", doc["id"], None, {"number": number, "total": total})
        account_name = customer.get("name") or data.customer_name or "نقدي"
        notification_title = f"فاتورة مبيعات {number}"
        notification_message = await _render_message_template("sale_notification", {
            "number": number,
            "amount": total,
            "account_name": account_name,
            "invoice_type": data.sale_type,
            "paid": paid,
            "remaining": remaining,
            "description": data.notes or "—",
            "balance_after": balance_after,
        })
        sale_snapshot = clean_doc({**doc, "balance_after": balance_after})
        notification_details = {
            "operation": "sale",
            "operation_id": doc["id"],
            "customer_id": customer.get("id"),
            "amount": total,
            "account_name": account_name,
            "invoice_type": data.sale_type,
            "paid": paid,
            "remaining": remaining,
            "description": data.notes or "",
            "balance_after": balance_after,
            "document": {
                "type": "sale",
                "sale": sale_snapshot,
                "customer": {
                    "id": customer.get("id"),
                    "name": customer.get("name") or account_name,
                    "phone": customer.get("phone") or "",
                    "customer_type": customer.get("customer_type") or "customer",
                    "balance": balance_after,
                },
            },
        }
        await notify(notification_title, notification_message, "info", details=notification_details)
        await notify_customer_account(customer.get("id"), notification_title, notification_message, "info", notification_details)
    except Exception as exc:
        logger.warning("sale post-commit notification/audit failed: %s", exc)
    return clean_doc({**doc, "balance_after": balance_after})

@api.get("/sales")
async def list_sales(q: Optional[str] = None, limit: int = 2000, offset: int = 0, user=Depends(require_perm("sales"))):
    """List sales invoices.

    A search term matches any of: the invoice number, the account name, the
    account phone number, or a card number sold inside the invoice.
    """
    query: Dict[str, Any] = {}
    needle = str(q or "").strip()
    if needle:
        rx = {"$regex": _re.escape(needle), "$options": "i"}
        matched_ids = [
            row.get("id")
            for row in await db.customers.find({"$or": [{"name": rx}, {"phone": rx}]}, {"id": 1}).to_list(500)
            if row.get("id")
        ]
        ors: List[Dict[str, Any]] = [
            {"number": rx},
            {"customer_name": rx},
            {"account_phone": rx},
            {"customer_phone": rx},
            {"items.card_numbers": rx},
            {"items.numbers": rx},
        ]
        if matched_ids:
            ors.append({"customer_id": {"$in": matched_ids}})
        query = {"$or": ors}
    limit = min(max(int(limit or 2000), 1), 5000)
    offset = max(int(offset or 0), 0)
    items = await db.sales.find(query).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    return [clean_doc(s) for s in items]

@api.get("/receipts/{rid}")
async def get_receipt(rid: str, user=Depends(require_perm("receipts"))):
    """Single receipt/voucher, used by the notification preview."""
    doc = await db.receipts.find_one({"$or": [{"id": rid}, {"number": rid}]})
    if not doc:
        raise HTTPException(status_code=404, detail="السند غير موجود")
    doc = clean_doc(doc)
    if doc.get("party_id") and not doc.get("party_name"):
        party = await db.customers.find_one({"id": doc.get("party_id")}, {"name": 1, "phone": 1})
        if party:
            doc["party_name"] = party.get("name")
            doc.setdefault("party_phone", party.get("phone"))
    return doc

@api.get("/transfers/{tid}")
async def get_transfer(tid: str, user=Depends(require_perm("receipts"))):
    """Single transfer, used by the notification preview (also covers legacy
    quick-recharge receipts stored in the receipts collection)."""
    doc = await db.transfers.find_one({"$or": [{"id": tid}, {"number": tid}]})
    if not doc:
        legacy = await db.receipts.find_one({"$or": [{"id": tid}, {"number": tid}]})
        if not legacy:
            raise HTTPException(status_code=404, detail="التحويل غير موجود")
        doc = {
            "id": legacy.get("id"), "number": legacy.get("number"),
            "source_type": "cash", "source_id": "cash", "source_name": "الصندوق",
            "dest_type": "customer", "dest_id": legacy.get("party_id"), "dest_name": legacy.get("party_name", ""),
            "amount": legacy.get("amount", 0), "description": legacy.get("description", ""),
            "operation_type": "quick_recharge", "channel": legacy.get("channel"),
            "status": legacy.get("status", "active"), "created_at": legacy.get("created_at", ""),
        }
    doc = clean_doc(doc)
    ids = [x for x in [doc.get("source_id"), doc.get("dest_id"), doc.get("sender_id"), doc.get("recipient_id")] if x]
    if ids:
        parties = {c.get("id"): c for c in await db.customers.find({"id": {"$in": ids}}).to_list(len(ids))}
        for prefix, id_key, name_key in (("source", "source_id", "source_name"), ("dest", "dest_id", "dest_name")):
            party = parties.get(doc.get(id_key)) or {}
            if party.get("name") and not doc.get(name_key):
                doc[name_key] = party.get("name")
            if party.get("phone"):
                doc.setdefault(f"{prefix}_phone", party.get("phone"))
        if doc.get("sender_id"):
            doc.setdefault("source_name", parties.get(doc.get("sender_id"), {}).get("name"))
        if doc.get("recipient_id"):
            doc.setdefault("dest_name", parties.get(doc.get("recipient_id"), {}).get("name"))
    doc.setdefault("reference", doc.get("number"))
    return doc

@api.get("/sales/{sid}")
async def get_sale(sid: str, user=Depends(require_perm("sales"))):
    doc = await db.sales.find_one({"$or": [{"id": sid}, {"number": sid}]})
    if not doc: raise HTTPException(status_code=404, detail="غير موجود")
    return clean_doc(doc)

@api.post("/sales/{sid}/cancel")
@serialized_financial_operation
async def cancel_sale(sid: str, user=Depends(require_perm("delete_ops"))):
    doc = await db.sales.find_one({"id": sid})
    if not doc: raise HTTPException(status_code=404, detail="غير موجود")
    if doc.get("status") == "cancelled":
        return clean_doc(doc)
    for item in doc.get("items") or []:
        numbers = item.get("card_numbers") or []
        if numbers:
            reversible = await db.cards.count_documents({"number": {"$in": numbers}, "status": "sold", "sold_to": doc.get("customer_id")})
            if reversible != len(numbers):
                raise HTTPException(status_code=409, detail="لا يمكن إلغاء الفاتورة لأن بعض كروتها استُخدمت أو تغيرت حالتها.")
        residual = int(item.get("quantity", 0) or 0) - len(numbers)
        if residual > 0:
            stock = await db.stock.find_one({"category_id": item.get("category_id")})
            if not stock or int(stock.get("sold", 0) or 0) < residual:
                raise HTTPException(status_code=409, detail="لا يمكن إلغاء الفاتورة بسبب تعارض في رصيد المخزون.")
    await _reverse_sale_inventory(doc.get("items") or [])
    try:
        if doc.get("customer_id") and doc.get("number"):
            await _remove_ledger_by_op("customer", doc["customer_id"], doc["number"])
        await db.sales.update_one({"id": sid}, {"$set": {"status": "cancelled", "cancelled_at": now_iso(), "cancelled_by": user.get("username"), "inventory_reversed_at": now_iso()}})
    except Exception:
        await _restore_sale_inventory(doc.get("items") or [], doc.get("customer_id"))
        if doc.get("customer_id") and doc.get("number") and doc.get("sale_type") == "credit" and doc.get("remaining", 0):
            await _adjust_party_balance("customer", doc["customer_id"], float(doc.get("remaining") or 0), doc["number"], f"فاتورة مبيعات {doc['number']}")
        raise
    try:
        _af_sa = audit_fields(doc, ("number", "customer_name", "total", "status")) or None
        await audit_log(user, "cancel", "sale", sid, _af_sa,
                        {"status": "cancelled", "cancelled_by": user.get("username")})
    except Exception as exc:
        logger.warning("sale cancel audit failed: %s", exc)
    return {"ok": True}

@api.delete("/sales/{sid}")
@serialized_financial_operation
async def delete_sale(sid: str, user=Depends(require_perm("delete_ops"))):
    doc = await db.sales.find_one({"id": sid})
    if not doc:
        raise HTTPException(status_code=404, detail="غير موجود")
    if doc.get("status") != "cancelled":
        for item in doc.get("items") or []:
            numbers = item.get("card_numbers") or []
            if numbers:
                reversible = await db.cards.count_documents({"number": {"$in": numbers}, "status": "sold", "sold_to": doc.get("customer_id")})
                if reversible != len(numbers):
                    raise HTTPException(status_code=409, detail="لا يمكن حذف الفاتورة لأن بعض كروتها استُخدمت أو تغيرت حالتها.")
            residual = int(item.get("quantity", 0) or 0) - len(numbers)
            if residual > 0:
                stock = await db.stock.find_one({"category_id": item.get("category_id")})
                if not stock or int(stock.get("sold", 0) or 0) < residual:
                    raise HTTPException(status_code=409, detail="لا يمكن حذف الفاتورة بسبب تعارض في رصيد المخزون.")

        inventory_reversed = False
        ledger_removed = False
        try:
            await _reverse_sale_inventory(doc.get("items") or [])
            inventory_reversed = True
            if doc.get("customer_id") and doc.get("number"):
                await _remove_ledger_by_op("customer", doc["customer_id"], doc["number"])
                ledger_removed = True
            await db.sales.delete_one({"id": sid})
        except Exception:
            if inventory_reversed:
                await _restore_sale_inventory(doc.get("items") or [], doc.get("customer_id"))
            if ledger_removed and doc.get("customer_id") and doc.get("sale_type") == "credit" and doc.get("remaining", 0):
                await _adjust_party_balance("customer", doc["customer_id"], float(doc.get("remaining") or 0), doc["number"], f"فاتورة مبيعات {doc['number']}")
            raise
    else:
        await db.sales.delete_one({"id": sid})

    try:
        await db.incentive_earnings.delete_many({"source_sale_id": sid, "status": "pending"})
        await audit_log(user, f"حذف فاتورة مبيعات {doc.get('number','')}", "sale", sid, {"number": doc.get("number"), "total": doc.get("total")}, None)
    except Exception as exc:
        logger.warning("sale delete post-commit cleanup/audit failed: %s", exc)
    return {"ok": True}

@api.delete("/purchases/{pid}")
@serialized_financial_operation
async def delete_purchase(pid: str, user=Depends(require_perm("delete_ops"))):
    doc = await db.purchases.find_one({"id": pid})
    if not doc:
        raise HTTPException(status_code=404, detail="غير موجود")
    if doc.get("status") == "cancelled":
        await db.purchases.delete_one({"id": pid})
        return {"ok": True}

    card_numbers = [number for item in (doc.get("items") or []) for number in (item.get("card_numbers") or [])]
    card_snapshots = await db.cards.find({"number": {"$in": card_numbers}}).to_list(len(card_numbers) or 1)
    if len(card_snapshots) != len(card_numbers) or any(card.get("status") != "available" for card in card_snapshots):
        raise HTTPException(status_code=409, detail="لا يمكن حذف الفاتورة لأن بعض الكروت المشتراة بيعت أو استُخدمت.")

    quantity_items = [item for item in (doc.get("items") or []) if not (item.get("card_numbers") or [])]
    stock_snapshots = {}
    for item in quantity_items:
        stock = await db.stock.find_one({"category_id": item.get("category_id")})
        quantity = int(item.get("quantity", 0) or 0)
        if not stock or int(stock.get("total", 0) or 0) - quantity < int(stock.get("sold", 0) or 0):
            raise HTTPException(status_code=409, detail="لا يمكن حذف الفاتورة لأن جزءاً من كميتها بيع أو استُخدم.")
        stock_snapshots[item.get("category_id")] = stock

    ledger_removed = False
    try:
        await _reverse_purchase_inventory(doc.get("items") or [], pid)
        if doc.get("supplier_id") and doc.get("number"):
            await _remove_ledger_by_op("supplier", doc["supplier_id"], doc["number"])
            ledger_removed = True
        await db.purchases.delete_one({"id": pid})
    except Exception:
        if card_snapshots:
            await db.cards.delete_many({"number": {"$in": card_numbers}})
            await db.cards.insert_many(card_snapshots)
        for category_id, snapshot in stock_snapshots.items():
            await db.stock.replace_one({"category_id": category_id}, snapshot, upsert=True)
        if ledger_removed and doc.get("supplier_id") and doc.get("remaining", 0):
            await _adjust_party_balance("supplier", doc["supplier_id"], -float(doc.get("remaining") or 0), doc["number"], f"فاتورة مشتريات {doc['number']}")
        raise
    try:
        await audit_log(user, f"حذف فاتورة مشتريات {doc.get('number','')}", "purchase", pid, {"number": doc.get("number"), "total": doc.get("total")}, None)
    except Exception as exc:
        logger.warning("purchase delete audit failed: %s", exc)
    return {"ok": True}


# ================= RETURNS =================
async def _return_cashbox(bank_account_id: Optional[str], amount: float, kind: str, return_id: str, number: str, description: str, user: dict):
    if not bank_account_id:
        raise HTTPException(status_code=400, detail="اختر الحساب النقدي أو البنكي الذي ستتم عليه التسوية.")
    bank = await db.bank_accounts.find_one({"id": bank_account_id, "active": True})
    if not bank:
        raise HTTPException(status_code=404, detail="الحساب النقدي أو البنكي غير موجود أو غير مفعّل.")
    cashbox = await _ensure_bank_cashbox(bank, user.get("username"))
    receipt = {
        "id": str(uuid.uuid4()), "number": number,
        "type": "return_cash_receipt", "kind": kind,
        "party_type": "customer" if kind == "payment" else "supplier",
        "party_id": None, "party_name": "مرتجع مبيعات" if kind == "payment" else "مرتجع مشتريات",
        "amount": float(amount), "description": description,
        "cashbox_id": cashbox.get("id"), "cashbox_name": cashbox.get("name"),
        "return_id": return_id, "receipt_kind": "sales_return" if kind == "payment" else "purchase_return",
        "user_id": user.get("id"), "username": user.get("username"),
        "status": "active", "created_at": now_iso(), "operation_at": now_iso(),
    }
    await db.receipts.insert_one(receipt)
    return receipt


async def _validate_return_items(items: List[ReturnItemIn], for_sales: bool):
    if not items:
        raise HTTPException(status_code=400, detail="أضف صنفاً واحداً على الأقل إلى المرتجع.")
    final = []
    for item in items:
        category = await db.card_categories.find_one({"id": item.category_id})
        if not category:
            raise HTTPException(status_code=404, detail=f"فئة المخزون غير موجودة: {item.category_name or item.category_id}")
        if is_balance_category(category):
            raise HTTPException(status_code=400, detail="فئة الرصيد لا تدخل ضمن مرتجعات الكروت.")
        numbers = [(n or "").strip() for n in (item.card_numbers or []) if (n or "").strip()]
        if item.use_numbered:
            if len(numbers) != int(item.quantity) or len(set(numbers)) != len(numbers):
                raise HTTPException(status_code=400, detail="عدد أرقام الكروت يجب أن يساوي الكمية ولا يتكرر.")
            statuses = await db.cards.find({"number": {"$in": numbers}}, {"number": 1, "status": 1, "category_id": 1}).to_list(len(numbers))
            if len(statuses) != len(numbers) or any(row.get("category_id") != item.category_id for row in statuses):
                raise HTTPException(status_code=409, detail="أحد أرقام الكروت غير موجود في الفئة المحددة.")
            expected = "sold" if for_sales else "available"
            if any(row.get("status") != expected for row in statuses):
                raise HTTPException(status_code=409, detail="حالة أحد الكروت لا تسمح بهذا المرتجع.")
        else:
            stock = await db.stock.find_one({"category_id": item.category_id})
            available = int((stock or {}).get("sold", 0) or 0) if for_sales else int((stock or {}).get("total", 0) or 0) - int((stock or {}).get("sold", 0) or 0)
            if available < int(item.quantity):
                raise HTTPException(status_code=409, detail="الكمية المتاحة للمرتجع غير كافية في المخزون.")
        final.append({**item.model_dump(), "category_name": category.get("name") or item.category_name, "card_numbers": numbers, "total": int(item.quantity) * float(item.price)})
    return final


@api.post("/sales-returns")
@idempotent_operation("sales_return", "sales_returns")
@serialized_financial_operation
async def create_sales_return(data: SalesReturnIn, user=Depends(require_perm("sales"))):
    if data.idempotency_key:
        existing = await db.sales_returns.find_one({"idempotency_key": data.idempotency_key})
        if existing:
            return clean_doc(existing)
    if data.settlement_type == "customer_balance" and not data.customer_id:
        raise HTTPException(status_code=400, detail="اختر العميل عند تسوية مرتجع المبيعات على الحساب.")
    customer = await db.customers.find_one({"id": data.customer_id}) if data.customer_id else None
    if data.customer_id and not customer:
        raise HTTPException(status_code=404, detail="حساب العميل غير موجود.")
    items = await _validate_return_items(data.items, True)
    total = round(sum(float(row["total"]) for row in items), 6)
    if total <= 0:
        raise HTTPException(status_code=400, detail="قيمة المرتجع غير صالحة.")
    number = (data.number or "").strip() or await next_gwd_number()
    doc = {"id": str(uuid.uuid4()), "number": number, "type": "sales_return", "customer_id": data.customer_id,
           "customer_name": (customer or {}).get("name") or data.customer_name or "عميل نقدي", "settlement_type": data.settlement_type,
           "bank_account_id": data.bank_account_id, "items": items, "total": total, "notes": data.notes,
           "manager_approved": bool(data.manager_approved), "status": "active", "idempotency_key": data.idempotency_key,
           "user_id": user.get("id"), "username": user.get("username"), "created_at": now_iso(), "operation_at": now_iso()}
    changed_cards, changed_stock, ledger_changed, receipt = [], [], False, None
    try:
        for item in items:
            numbers = item.get("card_numbers") or []
            if numbers:
                result = await db.cards.update_many({"number": {"$in": numbers}, "status": "sold"}, {"$set": {"status": "available", "sold_at": None, "sold_to": None}})
                if result.modified_count != len(numbers):
                    raise HTTPException(status_code=409, detail="تغيرت حالة أحد الكروت أثناء الحفظ.")
                changed_cards.extend(numbers)
            else:
                await db.stock.update_one({"category_id": item["category_id"]}, {"$inc": {"sold": -int(item["quantity"])}})
                changed_stock.append((item["category_id"], int(item["quantity"])))
        if data.settlement_type == "customer_balance":
            await _adjust_party_balance("customer", data.customer_id, -total, number, f"مرتجع مبيعات {number}")
            ledger_changed = True
        else:
            receipt = await _return_cashbox(data.bank_account_id, total, "payment", doc["id"], number, f"صرف مرتجع مبيعات {number}", user)
        await db.sales_returns.insert_one(doc)
        if changed_cards:
            try:
                _ret_rows = await db.cards.find({"number": {"$in": changed_cards}}, {"id": 1, "number": 1}).to_list(len(changed_cards))
                await log_card_events(_ret_rows, "returned", user.get("username"),
                                      {"return_number": number}, f"مرتجع مبيعات {number}")
            except Exception as exc:
                logger.warning("card return event log failed: %s", exc)
    except Exception:
        if receipt: await db.receipts.delete_one({"id": receipt["id"]})
        if ledger_changed: await _remove_ledger_by_op("customer", data.customer_id, number)
        if changed_cards: await db.cards.update_many({"number": {"$in": changed_cards}, "status": "available"}, {"$set": {"status": "sold", "sold_at": now_iso(), "sold_to": data.customer_id}})
        for category_id, qty in changed_stock: await db.stock.update_one({"category_id": category_id}, {"$inc": {"sold": qty}})
        raise
    await audit_log(user, "create", "sales_return", doc["id"], None, {"number": number, "total": total, "settlement_type": data.settlement_type})
    return clean_doc(doc)


@api.get("/sales-returns")
async def list_sales_returns(limit: int = 2000, user=Depends(require_perm("sales"))):
    items = await db.sales_returns.find({"status": "active"}).sort("created_at", -1).limit(min(max(int(limit or 2000), 1), 5000)).to_list(min(max(int(limit or 2000), 1), 5000))
    return [clean_doc(item) for item in items]


@api.post("/purchase-returns")
@idempotent_operation("purchase_return", "purchase_returns")
@serialized_financial_operation
async def create_purchase_return(data: PurchaseReturnIn, user=Depends(require_perm("purchases"))):
    if data.idempotency_key:
        existing = await db.purchase_returns.find_one({"idempotency_key": data.idempotency_key})
        if existing:
            return clean_doc(existing)
    if data.settlement_type == "supplier_balance" and not data.supplier_id:
        raise HTTPException(status_code=400, detail="اختر المورد عند تسوية مرتجع المشتريات على الحساب.")
    supplier = await db.suppliers.find_one({"id": data.supplier_id}) if data.supplier_id else None
    if data.supplier_id and not supplier:
        raise HTTPException(status_code=404, detail="حساب المورد غير موجود.")
    items = await _validate_return_items(data.items, False)
    total = round(sum(float(row["total"]) for row in items), 6)
    if total <= 0:
        raise HTTPException(status_code=400, detail="قيمة المرتجع غير صالحة.")
    number = (data.number or "").strip() or await next_gwd_number()
    doc = {"id": str(uuid.uuid4()), "number": number, "type": "purchase_return", "supplier_id": data.supplier_id,
           "supplier_name": (supplier or {}).get("name") or data.supplier_name or "مورد نقدي", "settlement_type": data.settlement_type,
           "bank_account_id": data.bank_account_id, "items": items, "total": total, "notes": data.notes,
           "manager_approved": bool(data.manager_approved), "status": "active", "idempotency_key": data.idempotency_key,
           "user_id": user.get("id"), "username": user.get("username"), "created_at": now_iso(), "operation_at": now_iso()}
    deleted_cards, stock_changes, ledger_changed, receipt = [], [], False, None
    try:
        for item in items:
            numbers = item.get("card_numbers") or []
            if numbers:
                snapshots = await db.cards.find({"number": {"$in": numbers}, "status": "available"}).to_list(len(numbers))
                if len(snapshots) != len(numbers): raise HTTPException(status_code=409, detail="تغيرت حالة أحد الكروت أثناء الحفظ.")
                await db.cards.delete_many({"number": {"$in": numbers}, "status": "available"})
                deleted_cards.extend(snapshots)
            else:
                stock = await db.stock.find_one({"category_id": item["category_id"]})
                if not stock or int(stock.get("total", 0) or 0) - int(item["quantity"]) < int(stock.get("sold", 0) or 0):
                    raise HTTPException(status_code=409, detail="لا يمكن إرجاع كمية استُخدمت أو بيعت.")
                await db.stock.update_one({"category_id": item["category_id"]}, {"$inc": {"total": -int(item["quantity"])}})
                stock_changes.append((item["category_id"], int(item["quantity"])))
        if data.settlement_type == "supplier_balance":
            await _adjust_party_balance("supplier", data.supplier_id, total, number, f"مرتجع مشتريات {number}")
            ledger_changed = True
        else:
            receipt = await _return_cashbox(data.bank_account_id, total, "receipt", doc["id"], number, f"قبض مرتجع مشتريات {number}", user)
        await db.purchase_returns.insert_one(doc)
    except Exception:
        if receipt: await db.receipts.delete_one({"id": receipt["id"]})
        if ledger_changed: await _remove_ledger_by_op("supplier", data.supplier_id, number)
        if deleted_cards: await db.cards.insert_many(deleted_cards)
        for category_id, qty in stock_changes: await db.stock.update_one({"category_id": category_id}, {"$inc": {"total": qty}})
        raise
    await audit_log(user, "create", "purchase_return", doc["id"], None, {"number": number, "total": total, "settlement_type": data.settlement_type})
    return clean_doc(doc)


@api.get("/purchase-returns")
async def list_purchase_returns(limit: int = 2000, user=Depends(require_perm("purchases"))):
    items = await db.purchase_returns.find({"status": "active"}).sort("created_at", -1).limit(min(max(int(limit or 2000), 1), 5000)).to_list(min(max(int(limit or 2000), 1), 5000))
    return [clean_doc(item) for item in items]

@api.delete("/receipts/{rid}")
@serialized_financial_operation
async def delete_receipt(rid: str, user=Depends(require_perm("delete_ops"))):
    doc = await db.receipts.find_one({"id": rid})
    if not doc: raise HTTPException(status_code=404, detail="غير موجود")
    if doc.get("status") != "cancelled":
        pty = doc.get("party_type"); pid = doc.get("party_id")
        if pty in ("customer","supplier") and pid and doc.get("number"):
            await _remove_ledger_by_op(pty, pid, doc["number"])
    kind_ar = "قبض" if doc.get("kind") == "receipt" else "صرف"
    await db.receipts.delete_one({"id": rid})
    await audit_log(user, f"حذف سند {kind_ar} {doc.get('number','')}", "receipt", rid, {"number": doc.get("number"), "amount": doc.get("amount"), "kind": doc.get("kind")}, None)
    return {"ok": True}


class SaleEditIn(BaseModel):
    # legacy quick edit (still supported for partial updates)
    discount: Optional[float] = Field(default=None, ge=0)
    paid: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    # full edit (optional). When provided we reverse the old inventory/balance
    # effect and re-apply the new one atomically.
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    sale_type: Optional[str] = None
    items: Optional[List[SaleItemIn]] = None


async def _reverse_sale_inventory(items: list):
    for it in items or []:
        cards = it.get("card_numbers") or []
        if cards:
            await db.cards.update_many(
                {"number": {"$in": cards}},
                {"$set": {"status": "available", "sold_at": None, "sold_to": None}},
            )
        residual = int(it.get("quantity", 0)) - len(cards)
        if residual > 0:
            await db.stock.update_one(
                {"category_id": it.get("category_id")},
                {"$inc": {"sold": -residual}},
            )


async def _restore_sale_inventory(items: list, customer_id: Optional[str]):
    for item in items or []:
        cards = item.get("card_numbers") or []
        if cards:
            await db.cards.update_many(
                {"number": {"$in": cards}, "status": "available"},
                {"$set": {"status": "sold", "sold_at": now_iso(), "sold_to": customer_id}},
            )
        residual = int(item.get("quantity", 0) or 0) - len(cards)
        if residual > 0:
            await db.stock.update_one({"category_id": item.get("category_id")}, {"$inc": {"sold": residual}})


@api.put("/sales/{sid}")
@serialized_financial_operation
async def edit_sale(sid: str, data: SaleEditIn, user=Depends(require_perm("edit_ops"))):
    doc = await db.sales.find_one({"id": sid})
    if not doc: raise HTTPException(status_code=404, detail="غير موجود")
    if doc.get("status") != "active":
        raise HTTPException(status_code=400, detail="لا يمكن تعديل فاتورة ملغاة")

    # --------- FULL EDIT PATH (items provided) ---------
    if data.items is not None:
        if not data.items:
            raise HTTPException(status_code=400, detail="يجب إضافة بند واحد على الأقل إلى الفاتورة.")
        new_customer_id = data.customer_id or doc.get("customer_id")
        new_sale_type = data.sale_type or doc.get("sale_type", "credit")
        if new_sale_type not in ("cash", "credit"):
            raise HTTPException(status_code=400, detail="نوع الفاتورة غير صحيح")
        new_customer = await db.customers.find_one({"id": new_customer_id})
        if not new_customer:
            raise HTTPException(status_code=404, detail="حساب العميل غير موجود")
        preview_subtotal = sum(float(item.quantity) * float(item.price) for item in data.items)
        preview_discount = float(data.discount if data.discount is not None else doc.get("discount", 0) or 0)
        if preview_discount < 0 or preview_discount > preview_subtotal:
            raise HTTPException(status_code=400, detail="الخصم لا يمكن أن يكون سالباً أو أكبر من إجمالي الفاتورة.")
        preview_total = preview_subtotal - preview_discount
        preview_paid = float(data.paid if data.paid is not None else doc.get("paid", 0) or 0)
        if new_sale_type == "credit" and (preview_paid < 0 or preview_paid > preview_total):
            raise HTTPException(status_code=400, detail="المبلغ المدفوع يجب أن يكون بين صفر وإجمالي الفاتورة.")
        preview_remaining = 0.0 if new_sale_type == "cash" else preview_total - preview_paid
        effective_balance = float(new_customer.get("balance", 0) or 0)
        if new_customer_id == doc.get("customer_id") and doc.get("sale_type") == "credit":
            effective_balance -= float(doc.get("remaining", 0) or 0)
        _ensure_customer_credit_limit(
            new_customer,
            preview_remaining,
            f"لا يمكن تنفيذ التعديل لأنه يتجاوز سقف حساب العميل ({_customer_credit_limit(new_customer)})",
            base_balance=effective_balance,
        )
        await _validate_sale_inventory(data.items, doc.get("items") or [])
        # 1) remove OLD ledger entries + revert balance (keeps statement clean of reversal noise)
        await _reverse_sale_inventory(doc.get("items") or [])
        if doc.get("customer_id") and doc.get("number"):
            await _remove_ledger_by_op("customer", doc["customer_id"], doc["number"])
        # 2) compute new totals
        subtotal = 0.0
        items_final = []
        for it in data.items:
            line_total = it.quantity * it.price
            subtotal += line_total
            items_final.append({**it.model_dump(), "total": line_total})
        new_discount = float(data.discount if data.discount is not None else doc.get("discount", 0) or 0)
        requested_paid = float(data.paid if data.paid is not None else doc.get("paid", 0) or 0)
        new_total = subtotal - new_discount
        new_paid = new_total if new_sale_type == "cash" else min(max(requested_paid, 0), new_total)
        new_remaining = 0.0 if new_sale_type == "cash" else max(new_total - new_paid, 0)
        # 3) credit limit check on new customer
        if new_sale_type == "credit" and new_customer_id and new_remaining > 0:
            cust = await db.customers.find_one({"id": new_customer_id})
            if cust:
                limit = _customer_credit_limit(cust)
                try:
                    _ensure_customer_credit_limit(
                        cust,
                        new_remaining,
                        f"لا يمكن تنفيذ التعديل لأنه يتجاوز سقف حساب العميل ({limit})",
                    )
                except HTTPException:
                    # rollback the reversal we just did to keep DB consistent
                    if doc.get("customer_id") and doc.get("remaining", 0):
                        await _adjust_party_balance(
                            "customer", doc["customer_id"], float(doc.get("remaining") or 0),
                            doc["number"], f"استرجاع تأثير الفاتورة {doc['number']} بعد فشل التعديل",
                        )
                    # restore inventory
                    for it in doc.get("items") or []:
                        cards = it.get("card_numbers") or []
                        if cards:
                            await db.cards.update_many(
                                {"number": {"$in": cards}},
                                {"$set": {"status": "sold", "sold_to": doc.get("customer_id")}},
                            )
                        residual = int(it.get("quantity", 0)) - len(cards)
                        if residual > 0:
                            await db.stock.update_one({"category_id": it.get("category_id")}, {"$inc": {"sold": residual}})
                    raise
        # 4) apply NEW inventory (same rules as create_sale)
        for item in data.items:
            if item.use_numbered and item.card_numbers:
                for n in item.card_numbers:
                    card = await db.cards.find_one({"number": n, "status": "available"})
                    if not card:
                        raise HTTPException(status_code=400, detail=f"الكرت {n} غير متوفر")
                await db.cards.update_many(
                    {"number": {"$in": item.card_numbers}, "status": "available"},
                    {"$set": {"status": "sold", "sold_at": now_iso(), "sold_to": new_customer_id}},
                )
            else:
                stock = await db.stock.find_one({"category_id": item.category_id})
                avail = (stock or {}).get("total", 0) - (stock or {}).get("sold", 0) if stock else 0
                numbered_avail = await db.cards.count_documents({"category_id": item.category_id, "status": "available"})
                if avail + numbered_avail < item.quantity:
                    raise HTTPException(status_code=400, detail=f"الكمية غير متوفرة للفئة")
                take_from_qty = min(item.quantity, avail)
                if take_from_qty > 0:
                    await db.stock.update_one({"category_id": item.category_id}, {"$inc": {"sold": take_from_qty}})
                take_from_numbered = item.quantity - take_from_qty
                if take_from_numbered > 0:
                    pending = await db.cards.find({"category_id": item.category_id, "status": "available"}).limit(take_from_numbered).to_list(take_from_numbered)
                    ids = [c["id"] for c in pending]
                    await db.cards.update_many({"id": {"$in": ids}}, {"$set": {"status": "sold", "sold_at": now_iso(), "sold_to": new_customer_id}})
        # 5) apply NEW balance
        balance_after = None
        if new_sale_type == "credit" and new_customer_id and new_remaining > 0:
            balance_after = await _adjust_party_balance(
                "customer", new_customer_id, new_remaining,
                doc["number"], f"تعديل فاتورة {doc['number']}",
            )
        # 6) update the doc, keep same id + number + created_at
        cust_name = data.customer_name
        if new_customer_id and not cust_name:
            _c = await db.customers.find_one({"id": new_customer_id})
            cust_name = (_c or {}).get("name", doc.get("customer_name") or "")
        update = {
            "customer_id": new_customer_id, "customer_name": cust_name or doc.get("customer_name"),
            "sale_type": new_sale_type, "items": items_final,
            "subtotal": subtotal, "discount": new_discount, "total": new_total,
            "paid": new_paid, "remaining": new_remaining,
            "notes": data.notes if data.notes is not None else doc.get("notes"),
            "edited_at": now_iso(), "edited_by": user.get("username"),
        }
        await db.sales.update_one({"id": sid}, {"$set": update})
        await audit_log(user, "edit", "sale", sid,
                        {"customer_id": doc.get("customer_id"), "total": doc.get("total"), "items": doc.get("items")},
                        {"customer_id": new_customer_id, "total": new_total, "items": items_final})
        updated_doc = await db.sales.find_one({"id": sid})
        return clean_doc({**updated_doc, "balance_after": balance_after})

    # --------- LEGACY QUICK EDIT PATH (discount/paid/notes only) ---------
    subtotal = _numeric_amount(doc.get("subtotal"), 0.0)
    new_discount = _numeric_amount(data.discount if data.discount is not None else doc.get("discount"), 0.0)
    requested_paid = _numeric_amount(data.paid if data.paid is not None else doc.get("paid"), 0.0)
    if new_discount < 0 or new_discount > subtotal:
        raise HTTPException(status_code=400, detail="الخصم لا يمكن أن يكون سالباً أو أكبر من إجمالي الفاتورة.")
    new_total = subtotal - new_discount
    is_cash = doc.get("sale_type") == "cash"
    if not is_cash and (requested_paid < 0 or requested_paid > new_total):
        raise HTTPException(status_code=400, detail="المبلغ المدفوع يجب أن يكون بين صفر وإجمالي الفاتورة.")
    new_paid = new_total if is_cash else requested_paid
    new_remaining = 0.0 if is_cash else max(new_total - new_paid, 0)
    old_remaining = _numeric_amount(doc.get("remaining"), 0.0)
    diff = new_remaining - old_remaining
    if not is_cash and doc.get("customer_id") and diff != 0:
        customer = await db.customers.find_one({"id": doc["customer_id"]})
        if customer:
            _ensure_customer_credit_limit(customer, diff, "التعديل يتجاوز سقف حساب العميل")
        # Replace old ledger entry in place (no extra "تعديل" row in statement)
        await _remove_ledger_by_op("customer", doc["customer_id"], doc["number"])
        if new_remaining > 0:
            await _adjust_party_balance("customer", doc["customer_id"], new_remaining, doc["number"], f"فاتورة مبيعات {doc['number']}")
    update = {"discount": new_discount, "paid": new_paid, "total": new_total, "remaining": new_remaining,
              "notes": data.notes if data.notes is not None else doc.get("notes"),
              "edited_at": now_iso(), "edited_by": user.get("username")}
    await db.sales.update_one({"id": sid}, {"$set": update})
    await audit_log(user, "edit", "sale", sid, {"old": {"discount": doc.get("discount"), "paid": doc.get("paid")}}, update)
    updated_doc = await db.sales.find_one({"id": sid})
    return clean_doc(updated_doc)


class ReceiptEditIn(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    description: Optional[str] = None

@api.put("/receipts/{rid}")
@serialized_financial_operation
async def edit_receipt(rid: str, data: ReceiptEditIn, user=Depends(require_perm("edit_ops"))):
    doc = await db.receipts.find_one({"id": rid})
    if not doc: raise HTTPException(status_code=404, detail="غير موجود")
    old_amount = _numeric_amount(doc.get("amount"), 0.0)
    new_amount = _numeric_amount(data.amount if data.amount is not None else old_amount, 0.0)
    diff = new_amount - old_amount
    pty = doc.get("party_type"); pid = doc.get("party_id")
    sign = -1 if doc.get("kind") == "receipt" else 1
    kind_ar = "قبض" if doc.get("kind") == "receipt" else "صرف"
    if diff != 0:
        if pty == "customer" and sign * new_amount > 0:
            customer = await db.customers.find_one({"id": pid})
            if customer:
                current_without_old = _numeric_amount(customer.get("balance"), 0.0) - (sign * old_amount)
                _ensure_customer_credit_limit(customer, sign * new_amount, "تعديل السند يتجاوز سقف حساب العميل", base_balance=current_without_old)
        try:
            await _remove_ledger_by_op(pty, pid, doc.get("number",""))
            await _adjust_party_balance(pty, pid, sign * new_amount, doc["number"], f"سند {kind_ar} {doc['number']}", when=doc.get("created_at"))
        except Exception:
            await _remove_ledger_by_op(pty, pid, doc.get("number",""))
            await _adjust_party_balance(pty, pid, sign * old_amount, doc["number"], doc.get("description") or f"سند {kind_ar}", when=doc.get("created_at"))
            raise
    update = {"amount": new_amount,
              "description": data.description if data.description is not None else doc.get("description"),
              "edited_at": now_iso(), "edited_by": user.get("username")}
    try:
        await db.receipts.update_one({"id": rid}, {"$set": update})
    except Exception:
        if diff != 0:
            await _remove_ledger_by_op(pty, pid, doc.get("number",""))
            await _adjust_party_balance(pty, pid, sign * old_amount, doc["number"], doc.get("description") or f"سند {kind_ar}", when=doc.get("created_at"))
        raise
    try:
        await audit_log(user, "edit", "receipt", rid, {"old_amount": old_amount}, {"new_amount": new_amount})
    except Exception as exc:
        logger.warning("receipt edit audit failed: %s", exc)
    return {"ok": True}


# List customers with blocked info
@api.get("/customers/blocked/list")
async def blocked_customers(user=Depends(require_perm("customers"))):
    now = now_iso()
    blocks = await db.public_blocks.find({"blocked_until": {"$gt": now}}).to_list(1000)
    result = []
    for b in blocks:
        cust = await db.customers.find_one({"phone": b.get("phone")})
        result.append({
            "phone": b.get("phone"),
            "customer_name": (cust or {}).get("name", "غير معروف"),
            "customer_id": (cust or {}).get("id"),
            "failed_before_block": 5,
            "blocked_at": b.get("blocked_at"),
            "blocked_until": b.get("blocked_until"),
        })
    return result


# ================= PURCHASES =================
@api.post("/purchases")
@idempotent_operation("purchase", "purchases")
async def create_purchase(data: PurchaseIn, user=Depends(require_perm("purchases"))):
    if data.idempotency_key:
        existing = await db.purchases.find_one({"idempotency_key": data.idempotency_key})
        if existing:
            return clean_doc(existing)
    if data.purchase_type not in ("cash", "credit"):
        raise HTTPException(status_code=400, detail="يرجى اختيار نوع الفاتورة: نقد أو آجل.")
    if not data.items:
        raise HTTPException(status_code=400, detail="يجب إضافة بند واحد على الأقل إلى الفاتورة.")
    supplier = None
    if data.supplier_id:
        supplier = await db.suppliers.find_one({"id": data.supplier_id})
        if not supplier:
            raise HTTPException(status_code=404, detail="حساب المورد غير موجود.")
    if data.purchase_type == "credit" and not supplier:
        raise HTTPException(status_code=400, detail="يجب اختيار المورد للفاتورة الآجلة.")

    subtotal = sum(float(item.quantity) * float(item.price) for item in data.items)
    discount = float(data.discount or 0)
    if discount < 0 or discount > subtotal:
        raise HTTPException(status_code=400, detail="الخصم لا يمكن أن يكون سالباً أو أكبر من إجمالي الفاتورة.")
    total = subtotal - discount
    raw_paid = float(data.paid or 0)
    if data.purchase_type == "credit" and (raw_paid < 0 or raw_paid > total):
        raise HTTPException(status_code=400, detail="المبلغ المدفوع يجب أن يكون بين صفر وإجمالي الفاتورة.")
    paid = total if data.purchase_type == "cash" else raw_paid
    remaining = 0.0 if data.purchase_type == "cash" else total - paid
    if data.supplier_id:
        await _reject_duplicate_financial_operation("supplier", data.supplier_id, total, "فاتورة المشتريات", data.allow_duplicate)

    categories = {}
    seen_numbers = set()
    preview_ids = set()
    items_final = []
    for item in data.items:
        category = await db.card_categories.find_one({"id": item.category_id})
        if not category:
            raise HTTPException(status_code=404, detail=f"فئة المخزون غير موجودة: {item.category_name or item.category_id}")
        if is_balance_category(category):
            raise HTTPException(status_code=400, detail="فئة رصيد مالية ولا تدخل ضمن فواتير المشتريات")
        categories[item.category_id] = category
        numbers = [(number or "").strip() for number in (item.card_numbers or []) if (number or "").strip()]
        if item.card_pdf_preview_id:
            if item.card_pdf_preview_id in preview_ids:
                raise HTTPException(status_code=409, detail="لا يمكن استخدام معاينة PDF نفسها في أكثر من بند")
            preview = await _get_ready_card_pdf_preview(item.card_pdf_preview_id, item.category_id, user)
            numbers = [(number or "").strip() for number in (preview.get("numbers") or []) if (number or "").strip()]
            preview_ids.add(item.card_pdf_preview_id)
            item.use_numbered = True
            if len(numbers) != int(item.quantity):
                raise HTTPException(status_code=409, detail="تغيرت كمية الكروت بعد المعاينة؛ أعد معاينة ملف PDF")
        if item.use_numbered:
            if len(numbers) != int(item.quantity):
                raise HTTPException(status_code=400, detail="عدد أرقام الكروت يجب أن يساوي كمية البند.")
            if len(set(numbers)) != len(numbers) or any(number in seen_numbers for number in numbers):
                raise HTTPException(status_code=400, detail="توجد أرقام كروت مكررة داخل الفاتورة.")
            existing_number = await db.cards.find_one({"number": {"$in": numbers}}, {"number": 1})
            if existing_number:
                raise HTTPException(status_code=409, detail=f"رقم الكرت موجود مسبقاً: {existing_number.get('number', '')}")
            seen_numbers.update(numbers)
        row = item.model_dump()
        row["quantity"] = int(item.quantity)
        row["card_numbers"] = numbers
        row["total"] = int(item.quantity) * float(item.price)
        items_final.append(row)

    number = (data.number or "").strip() or await next_gwd_number()
    doc = {
        "id": str(uuid.uuid4()), "number": number, "type": "purchase",
        "supplier_id": data.supplier_id, "supplier_name": (supplier or {}).get("name") or data.supplier_name,
        "purchase_type": data.purchase_type, "items": items_final,
        "subtotal": subtotal, "discount": discount, "total": total,
        "paid": paid, "remaining": remaining, "notes": data.notes,
        "user_id": user["id"], "username": user.get("username"), "status": "active",
        "idempotency_key": data.idempotency_key, "local_id": data.local_id,
        "device_id": data.device_id, "created_at": now_iso(), "operation_at": now_iso(),
    }

    inserted_card_ids = []
    stock_changes = []
    purchase_inserted = False
    try:
        for item in items_final:
            category = categories[item["category_id"]]
            if item.get("use_numbered"):
                for card_number in item.get("card_numbers") or []:
                    card_id = str(uuid.uuid4())
                    await db.cards.insert_one({
                        "id": card_id, "number": card_number,
                        "category_id": item["category_id"], "category_name": category.get("name"),
                        "status": "available", "type": "numbered", "purchase_price": item["price"],
                        "supplier_id": data.supplier_id, "created_at": now_iso(), "created_by": user.get("username"),
                    })
                    inserted_card_ids.append(card_id)
            else:
                stock = await db.stock.find_one({"category_id": item["category_id"]})
                quantity = int(item["quantity"])
                if stock:
                    await db.stock.update_one({"category_id": item["category_id"]}, {"$inc": {"total": quantity}})
                    stock_changes.append((item["category_id"], quantity, False, None))
                else:
                    stock_id = str(uuid.uuid4())
                    await db.stock.insert_one({
                        "id": stock_id, "category_id": item["category_id"], "category_name": category.get("name"),
                        "total": quantity, "sold": 0, "used": 0, "created_at": now_iso(),
                    })
                    stock_changes.append((item["category_id"], quantity, True, stock_id))

        await db.purchases.insert_one(doc)
        purchase_inserted = True
        if preview_ids:
            await db.card_pdf_previews.update_many(
                {"id": {"$in": list(preview_ids)}, "status": "ready"},
                {"$set": {"status": "committed_to_purchase", "committed_purchase_id": doc["id"], "committed_at": now_iso(), "committed_by": user.get("username")}},
            )
        balance_after = None
        if data.purchase_type == "credit" and data.supplier_id and remaining > 0:
            balance_after = await _adjust_party_balance("supplier", data.supplier_id, -remaining, number, f"فاتورة مشتريات آجلة {number}")
    except Exception:
        if data.supplier_id:
            await _remove_ledger_by_op("supplier", data.supplier_id, number)
        if purchase_inserted:
            await db.purchases.delete_one({"id": doc["id"]})
        if inserted_card_ids:
            await db.cards.delete_many({"id": {"$in": inserted_card_ids}, "status": "available"})
        for category_id, quantity, created, stock_id in reversed(stock_changes):
            if created:
                deleted = await db.stock.delete_one({"id": stock_id, "sold": 0, "total": quantity})
                if not deleted.deleted_count:
                    await db.stock.update_one({"id": stock_id}, {"$inc": {"total": -quantity}})
            else:
                await db.stock.update_one({"category_id": category_id}, {"$inc": {"total": -quantity}})
        raise

    try:
        _af_pu = audit_fields(doc, ("number", "supplier_name", "total", "purchase_type",
                                    "remaining", "description")) or None
        await audit_log(user, "create", "purchase", doc["id"], None, _af_pu)
        account_name = doc.get("supplier_name") or "المورد"
        await notify(
            f"فاتورة مشتريات {number}",
            await _render_message_template("purchase_notification", {"number": number, "amount": total, "account_name": account_name, "invoice_type": data.purchase_type}),
            "info",
            details={"operation": "purchase", "amount": total, "account_name": account_name, "invoice_type": data.purchase_type},
        )
    except Exception as exc:
        logger.warning("purchase post-commit notification/audit failed: %s", exc)
    return clean_doc({**doc, "balance_after": balance_after})

class PurchaseEditIn(BaseModel):
    discount: Optional[float] = Field(default=None, ge=0)
    paid: Optional[float] = Field(default=None, ge=0)
    notes: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    purchase_type: Optional[str] = None
    items: Optional[List[SaleItemIn]] = None


async def _reverse_purchase_inventory(items: list, purchase_id: str):
    for it in items or []:
        cards = it.get("card_numbers") or []
        if it.get("use_numbered") and cards:
            # Delete cards that came from this purchase AND are still available
            await db.cards.delete_many({"number": {"$in": cards}, "status": "available"})
        else:
            # decrement stock.total by qty (but never below current sold)
            stock = await db.stock.find_one({"category_id": it.get("category_id")})
            if stock:
                new_total = max(stock.get("sold", 0), stock.get("total", 0) - int(it.get("quantity", 0)))
                await db.stock.update_one({"category_id": it.get("category_id")}, {"$set": {"total": new_total}})


@api.put("/purchases/{pid}")
@serialized_financial_operation
async def edit_purchase(pid: str, data: PurchaseEditIn, user=Depends(require_perm("edit_ops"))):
    doc = await db.purchases.find_one({"id": pid})
    if not doc: raise HTTPException(status_code=404, detail="غير موجود")
    if doc.get("status") != "active":
        raise HTTPException(status_code=400, detail="لا يمكن تعديل فاتورة ملغاة")

    # --------- FULL EDIT PATH ---------
    if data.items is not None:
        if not data.items:
            raise HTTPException(status_code=400, detail="يجب إضافة بند واحد على الأقل إلى الفاتورة.")
        new_supplier_id = data.supplier_id or doc.get("supplier_id")
        new_purchase_type = data.purchase_type or doc.get("purchase_type", "credit")
        if new_purchase_type not in ("cash", "credit"):
            raise HTTPException(status_code=400, detail="نوع الفاتورة غير صحيح")
        supplier = await db.suppliers.find_one({"id": new_supplier_id}) if new_supplier_id else None
        if new_purchase_type == "credit" and not supplier:
            raise HTTPException(status_code=400, detail="يجب اختيار مورد موجود للفاتورة الآجلة")
        preview_subtotal = sum(float(item.quantity) * float(item.price) for item in data.items)
        preview_discount = float(data.discount if data.discount is not None else doc.get("discount", 0) or 0)
        if preview_discount < 0 or preview_discount > preview_subtotal:
            raise HTTPException(status_code=400, detail="الخصم لا يمكن أن يكون سالباً أو أكبر من إجمالي الفاتورة.")
        preview_total = preview_subtotal - preview_discount
        preview_paid = float(data.paid if data.paid is not None else doc.get("paid", 0) or 0)
        if new_purchase_type == "credit" and (preview_paid < 0 or preview_paid > preview_total):
            raise HTTPException(status_code=400, detail="المبلغ المدفوع يجب أن يكون بين صفر وإجمالي الفاتورة.")
        old_numbers = {number for item in (doc.get("items") or []) for number in (item.get("card_numbers") or [])}
        new_numbers = []
        for item in data.items:
            if not await db.card_categories.find_one({"id": item.category_id}, {"_id": 1}):
                raise HTTPException(status_code=404, detail=f"فئة المخزون غير موجودة: {item.category_name or item.category_id}")
            if item.use_numbered:
                numbers = [(number or "").strip() for number in (item.card_numbers or []) if (number or "").strip()]
                if len(numbers) != int(item.quantity):
                    raise HTTPException(status_code=400, detail="عدد أرقام الكروت يجب أن يساوي كمية البند.")
                new_numbers.extend(numbers)
        if len(set(new_numbers)) != len(new_numbers):
            raise HTTPException(status_code=400, detail="توجد أرقام كروت مكررة داخل الفاتورة.")
        for number in new_numbers:
            existing = await db.cards.find_one({"number": number}, {"number": 1})
            if existing and number not in old_numbers:
                raise HTTPException(status_code=409, detail=f"رقم الكرت موجود مسبقاً: {number}")
        # 1) reverse OLD inventory + supplier balance
        await _reverse_purchase_inventory(doc.get("items") or [], pid)
        if doc.get("supplier_id") and doc.get("number"):
            await _remove_ledger_by_op("supplier", doc["supplier_id"], doc["number"])
        # 2) compute new totals + apply new inventory
        subtotal = 0.0
        items_final = []
        for it in data.items:
            line_total = it.quantity * it.price
            subtotal += line_total
            items_final.append({**it.model_dump(), "total": line_total})
            cat = await db.card_categories.find_one({"id": it.category_id})
            if not cat:
                continue
            if it.use_numbered and it.card_numbers:
                for n in it.card_numbers:
                    n = (n or "").strip()
                    if not n: continue
                    exists = await db.cards.find_one({"number": n})
                    if exists: continue
                    await db.cards.insert_one({
                        "id": str(uuid.uuid4()), "number": n,
                        "category_id": it.category_id, "category_name": cat.get("name"),
                        "status": "available", "type": "numbered",
                        "purchase_price": it.price,
                        "supplier_id": new_supplier_id,
                        "source_purchase_id": pid,
                        "created_at": now_iso(), "created_by": user.get("username"),
                    })
            else:
                stock = await db.stock.find_one({"category_id": it.category_id})
                if stock:
                    await db.stock.update_one({"category_id": it.category_id}, {"$inc": {"total": it.quantity}})
                else:
                    await db.stock.insert_one({
                        "id": str(uuid.uuid4()), "category_id": it.category_id,
                        "category_name": cat.get("name"),
                        "total": it.quantity, "sold": 0, "used": 0, "created_at": now_iso(),
                    })
        new_discount = float(data.discount if data.discount is not None else doc.get("discount", 0) or 0)
        requested_paid = float(data.paid if data.paid is not None else doc.get("paid", 0) or 0)
        new_total = subtotal - new_discount
        new_paid = new_total if new_purchase_type == "cash" else min(max(requested_paid, 0), new_total)
        new_remaining = 0.0 if new_purchase_type == "cash" else max(new_total - new_paid, 0)
        # 3) apply new supplier balance
        balance_after = None
        if new_purchase_type == "credit" and new_supplier_id and new_remaining > 0:
            balance_after = await _adjust_party_balance(
                "supplier", new_supplier_id, -new_remaining,
                doc["number"], f"تعديل فاتورة مشتريات {doc['number']}",
            )
        # 4) update the doc
        sup_name = data.supplier_name
        if new_supplier_id and not sup_name:
            _s = await db.suppliers.find_one({"id": new_supplier_id})
            sup_name = (_s or {}).get("name", doc.get("supplier_name") or "")
        update = {
            "supplier_id": new_supplier_id, "supplier_name": sup_name or doc.get("supplier_name"),
            "purchase_type": new_purchase_type,
            "items": items_final,
            "subtotal": subtotal, "discount": new_discount, "total": new_total,
            "paid": new_paid, "remaining": new_remaining,
            "notes": data.notes if data.notes is not None else doc.get("notes"),
            "edited_at": now_iso(), "edited_by": user.get("username"),
        }
        await db.purchases.update_one({"id": pid}, {"$set": update})
        await audit_log(user, "edit", "purchase", pid,
                        {"supplier_id": doc.get("supplier_id"), "total": doc.get("total"), "items": doc.get("items")},
                        {"supplier_id": new_supplier_id, "total": new_total, "items": items_final})
        updated_doc = await db.purchases.find_one({"id": pid})
        return clean_doc({**updated_doc, "balance_after": balance_after})

    # --------- LEGACY QUICK EDIT ---------
    subtotal = doc.get("subtotal", 0)
    new_discount = float(data.discount if data.discount is not None else doc.get("discount", 0) or 0)
    requested_paid = float(data.paid if data.paid is not None else doc.get("paid", 0) or 0)
    if new_discount < 0 or new_discount > subtotal:
        raise HTTPException(status_code=400, detail="الخصم لا يمكن أن يكون سالباً أو أكبر من إجمالي الفاتورة.")
    new_total = subtotal - new_discount
    is_cash = doc.get("purchase_type", "credit") == "cash"
    if not is_cash and (requested_paid < 0 or requested_paid > new_total):
        raise HTTPException(status_code=400, detail="المبلغ المدفوع يجب أن يكون بين صفر وإجمالي الفاتورة.")
    new_paid = new_total if is_cash else requested_paid
    new_remaining = 0.0 if is_cash else max(new_total - new_paid, 0)
    if doc.get("supplier_id") and doc.get("number"):
        await _remove_ledger_by_op("supplier", doc["supplier_id"], doc["number"])
        if not is_cash and new_remaining > 0:
            await _adjust_party_balance("supplier", doc["supplier_id"], -new_remaining, doc["number"], f"فاتورة مشتريات {doc['number']}")
    update = {"discount": new_discount, "paid": new_paid, "total": new_total, "remaining": new_remaining,
              "notes": data.notes if data.notes is not None else doc.get("notes"),
              "edited_at": now_iso(), "edited_by": user.get("username")}
    await db.purchases.update_one({"id": pid}, {"$set": update})
    await audit_log(user, "edit", "purchase", pid, {"old_total": doc.get("total")}, {"new_total": new_total})
    updated_doc = await db.purchases.find_one({"id": pid})
    return clean_doc(updated_doc)


@api.get("/purchases")
async def list_purchases(limit: int = 2000, offset: int = 0, user=Depends(require_perm("purchases"))):
    limit = min(max(int(limit or 2000), 1), 5000)
    offset = max(int(offset or 0), 0)
    items = await db.purchases.find().sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    return [clean_doc(p) for p in items]

@api.get("/purchases/{pid}")
async def get_purchase(pid: str, user=Depends(require_perm("purchases"))):
    doc = await db.purchases.find_one({"$or": [{"id": pid}, {"number": pid}]})
    if not doc: raise HTTPException(status_code=404)
    return clean_doc(doc)


# ================= RECEIPTS =================
@api.post("/receipts")
@idempotent_operation("receipt", "receipts")
async def create_receipt(data: ReceiptIn, user=Depends(require_perm("receipts"))):
    if data.idempotency_key:
        existing = await db.receipts.find_one({"idempotency_key": data.idempotency_key})
        if existing: return clean_doc(existing)
    number = (data.number or "").strip() or await next_gwd_number()
    # kind=receipt (قبض): reduce customer debt (-) or supplier balance
    # kind=payment (صرف): reduce supplier debt / customer prepay
    if data.party_type == "supplier":
        # المورد دائن (رصيد سالب = له). صرف/سداد للمورد يقلل ما علينا => يزيد الرصيد نحو الصفر (+).
        # قبض من المورد (استرجاع/تسبيق) => يزيد ما علينا => يقلل الرصيد (-).
        amount_sign = data.amount if data.kind == "payment" else -data.amount
    else:
        # عميل/نقطة بيع: القبض دائن (-)، والصرف المدفوع للحساب مدين (+).
        amount_sign = -data.amount if data.kind == "receipt" else data.amount
    if data.kind not in ("receipt", "payment"):
        raise HTTPException(status_code=400, detail="نوع السند غير مدعوم")
    if data.party_type not in ("customer", "supplier"):
        raise HTTPException(status_code=400, detail="نوع الحساب غير مدعوم")
    party_collection = db.customers if data.party_type == "customer" else db.suppliers
    party = await party_collection.find_one({"id": data.party_id})
    if not party:
        raise HTTPException(status_code=404, detail="الحساب المرتبط بالسند غير موجود")
    party_name = party.get("name") or data.party_name or ""
    if data.party_type == "customer" and amount_sign > 0:
        _ensure_customer_credit_limit(party, amount_sign)
    await _reject_duplicate_financial_operation(data.party_type, data.party_id, data.amount, "السند", data.allow_duplicate)
    created_at = business_timestamp(data.date)
    balance_after = await _adjust_party_balance(data.party_type, data.party_id, amount_sign, number, data.description or ("سند قبض" if data.kind=="receipt" else "سند صرف"), when=created_at)
    doc = {
        "id": str(uuid.uuid4()), "number": number,
        "type": "receipt_voucher" if data.kind == "receipt" else "payment_voucher",
        "kind": data.kind,
        "party_type": data.party_type, "party_id": data.party_id, "party_name": party_name,
        "amount": data.amount, "description": data.description,
        "user_id": user["id"], "username": user.get("username"),
        "status": "active", "idempotency_key": data.idempotency_key,
        "balance_after": balance_after,
        "created_at": created_at, "operation_at": now_iso(),
    }
    try:
        await db.receipts.insert_one(doc)
    except Exception:
        await _remove_ledger_by_op(data.party_type, data.party_id, number)
        raise
    kind_label = "سند قبض" if data.kind == "receipt" else "سند صرف"
    try:
        notification_message = await _render_message_template("voucher_notification", {
            "number": number,
            "amount": float(data.amount),
            "account_name": party_name,
            "voucher_type": kind_label,
            "description": data.description or "—",
            "balance_after": balance_after,
        })
        notification_details = {
            "operation": data.kind,
            "operation_id": doc["id"],
            "customer_id": data.party_id if data.party_type == "customer" else None,
            "voucher_type": kind_label,
            "number": number,
            "amount": float(data.amount),
            "account_name": party_name,
            "description": data.description or "",
            "balance_after": balance_after,
            "created_at": doc.get("created_at"),
        }
        if data.party_type == "customer":
            receipt_snapshot = clean_doc(doc)
            receipt_snapshot["created_at"] = receipt_display_time(doc.get("created_at"), doc.get("operation_at"))
            notification_details["document"] = {
                "type": "receipt",
                "receipt": receipt_snapshot,
                "party": {
                    "id": party.get("id"),
                    "name": party_name,
                    "phone": party.get("phone") or "",
                    "customer_type": party.get("customer_type") or "customer",
                    "balance": balance_after,
                },
            }
        await notify(kind_label, notification_message, "info", details=notification_details)
        if data.party_type == "customer":
            await notify_customer_account(data.party_id, kind_label, notification_message, "info", notification_details)
        _af_rc = dict(audit_fields(doc, ("number", "kind", "amount", "party_type",
                                         "party_name", "description")),
                      **receipt_audit_time(doc)) or None
        await audit_log(user, "create", "receipt", doc["id"], None, _af_rc)
    except Exception as exc:
        logger.warning("receipt post-commit notification/audit failed: %s", exc)
    doc["created_at"] = receipt_display_time(doc.get("created_at"), doc.get("operation_at"))
    return clean_doc(doc)

def receipt_display_time(created_at: Any, operation_at: Any) -> Any:
    """تاريخ السند كما هو مع وقت الإدخال الحقيقي بدل منتصف الليل.

    السندات تخزّن تاريخ السند فقط في created_at (منتصف ليل توقيت العمل)،
    ووقت الإدخال الفعلي في operation_at. هذه الدالة تدمجهما لقيمة عرض واحدة
    دون أي تغيير في البيانات المخزّنة.
    """
    created = parse_timestamp_utc(created_at)
    operation = parse_timestamp_utc(operation_at)
    if not created or not operation:
        return created_at
    local_date = created.astimezone(APP_TIMEZONE)
    local_time = operation.astimezone(APP_TIMEZONE)
    combined = local_date.replace(
        hour=local_time.hour, minute=local_time.minute,
        second=local_time.second, microsecond=0,
    )
    return combined.astimezone(timezone.utc).isoformat()


@api.get("/receipts")
async def list_receipts(limit: int = 2000, offset: int = 0, user=Depends(require_perm("receipts"))):
    limit = min(max(int(limit or 2000), 1), 5000)
    offset = max(int(offset or 0), 0)
    items = await db.receipts.find().sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    for item in items:
        item["created_at"] = receipt_display_time(item.get("created_at"), item.get("operation_at"))
        # Legacy automatic receipts predate receipt_kind; classify them for the
        # UI without rewriting financial history.
        if item.get("payment_verification_id") or item.get("auto_posted"):
            item.setdefault("receipt_kind", "automatic_payment")
    return [clean_doc(r) for r in items]


# ================= EXPENSES =================
@api.get("/expense-accounts")
async def list_expense_accounts(user=Depends(require_perm("expenses"))):
    items = await db.expense_accounts.find().sort("name", 1).to_list(500)
    result = []
    for account in items:
        item = clean_doc(account)
        if item.get("account_type"):
            custom = await db.account_types.find_one({"id": item["account_type"], "active": {"$ne": False}})
            if custom:
                item["account_type_name"] = custom.get("name", "")
                item["account_base_type"] = custom.get("base_type", "expense")
        result.append(item)
    return result

@api.post("/expense-accounts")
async def create_expense_account(data: ExpenseAccountIn, user=Depends(require_perm("expenses"))):
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="اسم الحساب مطلوب")
    if await db.expense_accounts.find_one({"name": data.name.strip()}):
        raise HTTPException(status_code=400, detail="الاسم مستخدم بالفعل")
    resolved_type = await _resolve_custom_account_type(data.account_type or "expense", allowed=("expense",))
    doc = {
        "id": str(uuid.uuid4()), "name": data.name.strip(),
        "notes": (data.notes or "").strip(),
        "account_type": resolved_type["id"],
        "created_at": now_iso(), "created_by": user.get("username"),
    }
    await db.expense_accounts.insert_one(doc)
    await audit_log(user, "create", "expense_account", doc["id"])
    return clean_doc(doc)

@api.delete("/expense-accounts/{acc_id}")
async def delete_expense_account(acc_id: str, user=Depends(require_perm("expenses"))):
    used = await db.expenses.count_documents({"account_id": acc_id, "status": {"$ne": "deleted"}})
    if used:
        raise HTTPException(status_code=400, detail=f"لا يمكن الحذف — الحساب مستخدم في {used} مصروف")
    r = await db.expense_accounts.delete_one({"id": acc_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="غير موجود")
    await audit_log(user, "delete", "expense_account", acc_id)
    return {"ok": True}

@api.get("/expenses")
async def list_expenses(user=Depends(require_perm("expenses"))):
    items = await db.expenses.find().sort("created_at", -1).limit(2000).to_list(2000)
    return [clean_doc(x) for x in items]

@api.post("/expenses")
@idempotent_operation("expense", "expenses")
async def create_expense(data: ExpenseIn, user=Depends(require_perm("expenses"))):
    if data.amount is None or data.amount <= 0:
        raise HTTPException(status_code=400, detail="المبلغ غير صالح")
    if data.idempotency_key:
        existing = await db.expenses.find_one({"idempotency_key": data.idempotency_key})
        if existing:
            return clean_doc(existing)
    acc = await db.expense_accounts.find_one({"id": data.account_id})
    if not acc:
        raise HTTPException(status_code=404, detail="حساب المصروف غير موجود")
    await _reject_duplicate_financial_operation("expense", data.account_id, data.amount, "المصروف", data.allow_duplicate)
    number = (data.number or "").strip() or await next_gwd_number()
    when = business_timestamp(data.date)
    doc = {
        "id": str(uuid.uuid4()), "number": number,
        "account_id": data.account_id, "account_name": acc.get("name", ""),
        "amount": float(data.amount),
        "description": (data.description or "").strip(),
        "user_id": user["id"], "username": user.get("username"),
        "idempotency_key": data.idempotency_key,
        "status": "active",
        "created_at": when, "operation_at": now_iso(),
    }
    await db.expenses.insert_one(doc)
    _af_ex = audit_fields(doc, ("amount", "account_name", "description", "date", "payment_method")) or None
    await audit_log(user, "create", "expense", doc["id"], None, _af_ex)
    return clean_doc(doc)

@api.delete("/expenses/{eid}")
@serialized_financial_operation
async def delete_expense(eid: str, user=Depends(require_perm("delete_ops"))):
    doc = await db.expenses.find_one({"id": eid})
    if not doc:
        raise HTTPException(status_code=404, detail="غير موجود")
    await db.expenses.update_one({"id": eid}, {"$set": {"status": "deleted", "deleted_at": now_iso(), "deleted_by": user.get("username")}})
    await audit_log(user, f"حذف مصروف {doc.get('number','')}", "expense", eid, {"number": doc.get("number"), "amount": doc.get("amount")}, None)
    return {"ok": True}


# ================= CASH BOX =================
@api.get("/cash/summary")
async def cash_summary(
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Compute cash box totals from all sources:
    IN  = cash sales + receipt vouchers + transfers TO cash
    OUT = cash purchases + payment vouchers + expenses + transfers FROM cash"""
    def in_range(iso: str) -> bool:
        return timestamp_in_business_range(iso, start, end) if (start or end) else True

    sales = [s for s in await db.sales.find({"status": "active", "sale_type": "cash"}).to_list(20000) if not s.get("cashbox_id")]
    purchases = await db.purchases.find({"status": "active", "purchase_type": "cash"}).to_list(20000)
    recs = [r for r in await db.receipts.find({"status": "active"}).to_list(20000) if not r.get("cashbox_id")]
    exps = await db.expenses.find({"status": "active"}).to_list(20000)
    trs = await db.transfers.find({"status": "active"}).to_list(20000)

    total_in_all = sum(s.get("total", 0) for s in sales) \
        + sum(r.get("amount", 0) for r in recs if r.get("kind") == "receipt") \
        + sum(t.get("amount", 0) for t in trs if t.get("dest_type") == "cash" and t.get("channel") != "admin_quick_recharge")
    total_out_all = sum(p.get("total", 0) for p in purchases) \
        + sum(r.get("amount", 0) for r in recs if r.get("kind") == "payment") \
        + sum(e.get("amount", 0) for e in exps) \
        + sum(t.get("amount", 0) for t in trs if t.get("source_type") == "cash" and t.get("channel") != "admin_quick_recharge")
    running_balance = total_in_all - total_out_all

    filt_in = sum(s.get("total", 0) for s in sales if in_range(s.get("created_at", ""))) \
              + sum(r.get("amount", 0) for r in recs if r.get("kind") == "receipt" and in_range(r.get("created_at", ""))) \
              + sum(t.get("amount", 0) for t in trs if t.get("dest_type") == "cash" and t.get("channel") != "admin_quick_recharge" and in_range(t.get("created_at", "")))
    filt_out = sum(p.get("total", 0) for p in purchases if in_range(p.get("created_at", ""))) \
               + sum(r.get("amount", 0) for r in recs if r.get("kind") == "payment" and in_range(r.get("created_at", ""))) \
               + sum(e.get("amount", 0) for e in exps if in_range(e.get("created_at", ""))) \
               + sum(t.get("amount", 0) for t in trs if t.get("source_type") == "cash" and t.get("channel") != "admin_quick_recharge" and in_range(t.get("created_at", "")))

    return {
        "range": {"start": start, "end": end},
        "balance": running_balance,
        "total_in": filt_in,
        "total_out": filt_out,
        "net": filt_in - filt_out,
        "counts": {
            "cash_sales": sum(1 for s in sales if in_range(s.get("created_at", ""))),
            "cash_purchases": sum(1 for p in purchases if in_range(p.get("created_at", ""))),
            "receipts": sum(1 for r in recs if r.get("kind") == "receipt" and in_range(r.get("created_at", ""))),
            "payments": sum(1 for r in recs if r.get("kind") == "payment" and in_range(r.get("created_at", ""))),
            "expenses": sum(1 for e in exps if in_range(e.get("created_at", ""))),
            "transfers_in": sum(1 for t in trs if t.get("dest_type") == "cash" and in_range(t.get("created_at", ""))),
            "transfers_out": sum(1 for t in trs if t.get("source_type") == "cash" and in_range(t.get("created_at", ""))),
        },
    }

@api.get("/cash/statement")
async def cash_statement(
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(require_perm("receipts")),
):
    """Returns every cash-affecting movement in the window, ordered by date."""
    def q(base):
        if start or end:
            base["$expr"] = mongo_business_date_expr(start, end)
        return base
    sales = [s for s in await db.sales.find(q({"status": "active", "sale_type": "cash"})).to_list(5000) if not s.get("cashbox_id")]
    purchases = await db.purchases.find(q({"status": "active", "purchase_type": "cash"})).to_list(5000)
    recs = [r for r in await db.receipts.find(q({"status": "active"})).to_list(5000) if not r.get("cashbox_id")]
    exps = await db.expenses.find(q({"status": "active"})).to_list(5000)
    trs = await db.transfers.find(q({"status": "active"})).to_list(5000)
    entries = []
    for s in sales:
        entries.append({"created_at": s["created_at"], "type": "cash_sale", "number": s.get("number"),
                        "description": f"مبيعات نقدية — {s.get('customer_name') or 'نقدي'}",
                        "in": s.get("total", 0), "out": 0})
    for p in purchases:
        entries.append({"created_at": p["created_at"], "type": "cash_purchase", "number": p.get("number"),
                        "description": f"مشتريات نقدية — {p.get('supplier_name') or 'نقدي'}",
                        "in": 0, "out": p.get("total", 0)})
    for r in recs:
        if r.get("kind") == "receipt":
            label = "تحويل رصيد" if r.get("channel") == "admin_quick_recharge" else "سند قبض"
            entries.append({"created_at": r["created_at"], "type": "transfer_balance" if r.get("channel") == "admin_quick_recharge" else "receipt", "number": r.get("number"),
                            "description": f"{label} — {r.get('party_name','')}",
                            "in": r.get("amount", 0), "out": 0})
        else:
            entries.append({"created_at": r["created_at"], "type": "payment", "number": r.get("number"),
                            "description": f"سند صرف — {r.get('party_name','')}",
                            "in": 0, "out": r.get("amount", 0)})
    for e in exps:
        entries.append({"created_at": e["created_at"], "type": "expense", "number": e.get("number"),
                        "description": f"مصروف — {e.get('account_name','')}" + (f" — {e.get('description')}" if e.get("description") else ""),
                        "in": 0, "out": e.get("amount", 0)})
    for t in trs:
        if t.get("channel") == "admin_quick_recharge":
            continue
        if t.get("dest_type") == "cash":
            entries.append({"created_at": t["created_at"], "type": "transfer_in", "number": t.get("number"),
                            "description": f"تحويل من {t.get('source_name','')}" + (f" — {t.get('description')}" if t.get("description") else ""),
                            "in": t.get("amount", 0), "out": 0})
        elif t.get("source_type") == "cash":
            entries.append({"created_at": t["created_at"], "type": "transfer_out", "number": t.get("number"),
                            "description": f"تحويل إلى {t.get('dest_name','')}" + (f" — {t.get('description')}" if t.get("description") else ""),
                            "in": 0, "out": t.get("amount", 0)})
    entries.sort(key=lambda x: parse_timestamp_utc(x.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
    running = 0.0
    for e in entries:
        running += (e["in"] or 0) - (e["out"] or 0)
        e["balance"] = running
    return {"range": {"start": start, "end": end}, "entries": entries,
            "total_in": sum(e["in"] for e in entries), "total_out": sum(e["out"] for e in entries)}


# ================= TRANSFERS =================
@api.post("/transfers")
@idempotent_operation("transfer", "transfers")
async def create_transfer(data: TransferIn, user=Depends(require_perm("receipts"))):
    if data.amount is None or data.amount <= 0:
        raise HTTPException(status_code=400, detail="المبلغ غير صالح")
    allowed = ("customer", "supplier", "expense", "cash", "cashbox")
    if data.source_type not in allowed or data.dest_type not in allowed:
        raise HTTPException(status_code=400, detail="نوع الحساب غير مدعوم")
    if data.source_type == data.dest_type and (data.source_id or "") == (data.dest_id or ""):
        raise HTTPException(status_code=400, detail="لا يمكن التحويل لنفس الحساب")
    if data.idempotency_key:
        existing = await db.transfers.find_one({"idempotency_key": data.idempotency_key})
        if existing: return clean_doc(existing)

    # Validate parties + fetch names
    source_name = data.source_name or ""
    dest_name = data.dest_name or ""
    source_phone = ""
    dest_phone = ""
    if data.source_type in ("customer", "supplier"):
        col = db.customers if data.source_type == "customer" else db.suppliers
        src = await col.find_one({"id": data.source_id})
        if not src: raise HTTPException(status_code=404, detail="الحساب المصدر غير موجود")
        source_name = src.get("name", source_name)
        source_phone = src.get("phone", "") or ""
        if data.block_negative:
            projected = _numeric_amount(src.get("balance"), 0.0) - _numeric_amount(data.amount, 0.0)
            if projected < 0:
                raise HTTPException(status_code=400, detail=f"الرصيد غير كافٍ في {source_name}")
    elif data.source_type == "expense":
        source = await db.expense_accounts.find_one({"id": data.source_id})
        if not source:
            raise HTTPException(status_code=404, detail="حساب المصروفات المصدر غير موجود")
        source_name = source.get("name") or source_name or "حساب المصروفات"
    elif data.source_type == "cashbox":
        source = await db.cashboxes.find_one({"id": data.source_id})
        if not source:
            raise HTTPException(status_code=404, detail="صندوق المحفظة المصدر غير موجود")
        if not source.get("active", True):
            raise HTTPException(status_code=409, detail="صندوق المحفظة المصدر غير مفعّل")
        source_name = source.get("name") or source_name or "صندوق المحفظة"
        source_balance = await _cashbox_balance(data.source_id)
        if data.block_negative and source_balance < _numeric_amount(data.amount, 0.0):
            raise HTTPException(status_code=400, detail=f"الرصيد غير كافٍ في {source_name}")
    else:
        source_name = source_name or "الصندوق"
    if data.dest_type in ("customer", "supplier"):
        col = db.customers if data.dest_type == "customer" else db.suppliers
        dst = await col.find_one({"id": data.dest_id})
        if not dst: raise HTTPException(status_code=404, detail="الحساب المستلم غير موجود")
        dest_name = dst.get("name", dest_name)
        dest_phone = dst.get("phone", "") or ""
    elif data.dest_type == "expense":
        dst = await db.expense_accounts.find_one({"id": data.dest_id})
        if not dst:
            raise HTTPException(status_code=404, detail="حساب المصروفات المستلم غير موجود")
        dest_name = dst.get("name") or dest_name or "حساب المصروفات"
    elif data.dest_type == "cashbox":
        dest = await db.cashboxes.find_one({"id": data.dest_id})
        if not dest:
            raise HTTPException(status_code=404, detail="صندوق المحفظة المستلم غير موجود")
        if not dest.get("active", True):
            raise HTTPException(status_code=409, detail="صندوق المحفظة المستلم غير مفعّل")
        dest_name = dest.get("name") or dest_name or "صندوق المحفظة"
    else:
        dest_name = dest_name or "الصندوق"

    account_ids = [
        account_id for account_type, account_id in (
            (data.source_type, data.source_id), (data.dest_type, data.dest_id)
        ) if account_type in ("customer", "supplier", "expense") and account_id
    ]
    if account_ids:
        for account_type, account_id in ((data.source_type, data.source_id), (data.dest_type, data.dest_id)):
            if account_type in ("customer", "supplier", "expense") and account_id:
                await _reject_duplicate_financial_operation(account_type, account_id, data.amount, "التحويل", data.allow_duplicate)

    when = business_timestamp(data.date)
    number = (data.number or "").strip() or await next_gwd_number()
    desc_src = data.description or f"تحويل إلى {dest_name}"
    desc_dst = data.description or f"تحويل من {source_name}"

    doc = {
        "id": str(uuid.uuid4()), "number": number,
        "source_type": data.source_type, "source_id": data.source_id, "source_name": source_name,
        "source_phone": source_phone,
        "dest_type": data.dest_type, "dest_id": data.dest_id, "dest_name": dest_name,
        "dest_phone": dest_phone,
        "amount": float(data.amount), "description": (data.description or "").strip(),
        "block_negative": bool(data.block_negative),
        "user_id": user["id"], "username": user.get("username"),
        "status": "active", "idempotency_key": data.idempotency_key,
        "created_at": when, "operation_at": now_iso(),
    }
    source_adjusted = False
    dest_adjusted = False
    try:
        if data.source_type in ("customer", "supplier"):
            await _adjust_party_balance(data.source_type, data.source_id, -data.amount, number, desc_src, when=when)
            source_adjusted = True
        if data.dest_type in ("customer", "supplier"):
            await _adjust_party_balance(data.dest_type, data.dest_id, data.amount, number, desc_dst, when=when)
            dest_adjusted = True
        await db.transfers.insert_one(doc)
    except Exception:
        if dest_adjusted:
            await _remove_ledger_by_op(data.dest_type, data.dest_id, number)
        if source_adjusted:
            await _remove_ledger_by_op(data.source_type, data.source_id, number)
        raise
    try:
        await notify(
            "تحويل بين الحسابات",
            f"المبلغ: {float(data.amount):,.2f} — من: {source_name} — إلى: {dest_name} — رقم العملية: {number}",
            "info",
            details={"operation": "transfer", "amount": float(data.amount), "source_name": source_name, "dest_name": dest_name, "number": number, "created_at": doc.get("created_at")},
        )
        await audit_log(user, "create", "transfer", doc["id"], None, {"amount": data.amount})
    except Exception as exc:
        logger.warning("transfer post-commit notification/audit failed: %s", exc)
    return clean_doc(doc)

@api.delete("/transfers/{tid}")
@serialized_financial_operation
async def delete_transfer(tid: str, user=Depends(require_perm("delete_ops"))):
    """Delete a transfer only after reversing every balance/stock effect.

    New quick-recharge transfers have companion receipt and stock-operation rows;
    older quick-recharges are exposed by GET /transfers as receipt-shaped rows.
    Both forms are handled here so the screen cannot delete only the display row
    while leaving a customer balance or balance-stock amount changed.
    """
    transfer = await db.transfers.find_one({"id": tid})
    legacy_receipt = None
    if not transfer:
        legacy_receipt = await db.receipts.find_one({"id": tid, "channel": "admin_quick_recharge"})
        if not legacy_receipt:
            raise HTTPException(status_code=404, detail="التحويل غير موجود")
        transfer = {
            "id": None,
            "number": legacy_receipt.get("number"),
            "dest_type": "customer",
            "dest_id": legacy_receipt.get("party_id"),
            "dest_name": legacy_receipt.get("party_name", ""),
            "amount": legacy_receipt.get("amount", 0),
            "channel": "admin_quick_recharge",
            "operation_type": "quick_recharge",
            "status": legacy_receipt.get("status", "active"),
        }

    if transfer.get("status") not in ("active", "done"):
        raise HTTPException(status_code=409, detail="تم حذف هذا التحويل أو لا يمكن حذفه حالياً")

    number = transfer.get("number") or transfer.get("reference")
    amount = _numeric_amount(transfer.get("amount"), 0.0)
    if not number or amount <= 0:
        raise HTTPException(status_code=409, detail="بيانات التحويل غير مكتملة ولا يمكن عكسه بأمان")

    is_quick_recharge = (
        transfer.get("channel") == "admin_quick_recharge"
        or transfer.get("operation_type") == "quick_recharge"
        or transfer.get("source_type") == "balance_stock"
    )

    if is_quick_recharge:
        recipient_id = transfer.get("dest_id") or transfer.get("party_id")
        stock_query = {"kind": "balance_transfer_out", "number": number}
        if transfer.get("id"):
            stock_query = {"kind": "balance_transfer_out", "$or": [{"transfer_id": transfer["id"]}, {"number": number}]}
        stock_op = await db.stock_ops.find_one(stock_query)
        category_id = (stock_op or {}).get("category_id") or transfer.get("source_id")
        stock = await db.stock.find_one({"category_id": category_id}) if category_id else None
        if not recipient_id or not stock_op or not stock:
            raise HTTPException(status_code=409, detail="لا يمكن حذف تحويل الرصيد لأن سجل المخزون المرتبط غير مكتمل")

        ledger_removed = False
        stock_restored = False
        try:
            await _remove_ledger_by_op("customer", recipient_id, number)
            ledger_removed = True
            changed = await db.stock.update_one({"category_id": category_id}, {"$inc": {"total": amount}})
            if changed.matched_count != 1:
                raise RuntimeError("تعذر استعادة مخزون الرصيد")
            stock_restored = True
            if transfer.get("id"):
                await db.transfers.delete_one({"id": transfer["id"]})
            if legacy_receipt:
                await db.receipts.delete_one({"id": legacy_receipt["id"]})
            else:
                receipt_query = {"channel": "admin_quick_recharge", "$or": [{"number": number}]}
                if transfer.get("idempotency_key"):
                    receipt_query["$or"].append({"idempotency_key": transfer["idempotency_key"]})
                await db.receipts.delete_many(receipt_query)
            await db.stock_ops.delete_one({"id": stock_op["id"]})
        except Exception:
            logger.exception("transfer delete failed for quick recharge %s", tid)
            raise
    else:
        source_type = transfer.get("source_type")
        source_id = transfer.get("source_id")
        dest_type = transfer.get("dest_type")
        dest_id = transfer.get("dest_id")
        try:
            if source_type in ("customer", "supplier") and source_id:
                await _remove_ledger_by_op(source_type, source_id, number)
            if dest_type in ("customer", "supplier") and dest_id:
                await _remove_ledger_by_op(dest_type, dest_id, number)
            await db.transfers.delete_one({"id": tid})
        except Exception:
            logger.exception("transfer delete failed for %s", tid)
            raise

    try:
        await audit_log(user, "delete", "transfer", tid, {
            "number": number, "amount": amount,
            "source_type": transfer.get("source_type", "balance_stock" if is_quick_recharge else None),
            "source_id": transfer.get("source_id"),
            "dest_type": transfer.get("dest_type"), "dest_id": transfer.get("dest_id"),
            "operation_type": transfer.get("operation_type"),
        }, None)
    except Exception as exc:
        logger.warning("transfer delete audit failed: %s", exc)
    return {"ok": True, "id": tid, "number": number}

@api.get("/transfers")
async def list_transfers(limit: int = 2000, offset: int = 0, user=Depends(require_perm("receipts"))):
    limit = min(max(int(limit or 2000), 1), 5000)
    offset = max(int(offset or 0), 0)
    items = await db.transfers.find({"status": {"$in": ["active", "done"]}}).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    customer_ids = {x.get("sender_id") for x in items if x.get("sender_id")} | {x.get("recipient_id") for x in items if x.get("recipient_id")}
    customer_ids |= {x.get("source_id") for x in items if x.get("source_type") == "customer" and x.get("source_id")}
    customer_ids |= {x.get("dest_id") for x in items if x.get("dest_type") == "customer" and x.get("dest_id")}
    party_map = {x.get("id"): x for x in await db.customers.find({"id": {"$in": list(customer_ids)}}).to_list(len(customer_ids))} if customer_ids else {}
    for item in items:
        if item.get("sender_id"):
            item.setdefault("source_type", "customer"); item.setdefault("source_id", item.get("sender_id")); item.setdefault("source_name", item.get("sender_name")); item.setdefault("source_phone", item.get("sender_phone")); item.setdefault("source_customer_type", item.get("sender_type"))
            src = party_map.get(item.get("sender_id"), {}); item.setdefault("source_name", src.get("name")); item.setdefault("source_phone", src.get("phone"))
        if item.get("recipient_id"):
            item.setdefault("dest_type", "customer"); item.setdefault("dest_id", item.get("recipient_id")); item.setdefault("dest_name", item.get("recipient_name")); item.setdefault("dest_phone", item.get("recipient_phone")); item.setdefault("dest_customer_type", item.get("recipient_type"))
            dst = party_map.get(item.get("recipient_id"), {}); item.setdefault("dest_name", dst.get("name")); item.setdefault("dest_phone", dst.get("phone"))
        item.setdefault("reference", item.get("number"))
        item.setdefault("description", None)
    # Older quick-recharge operations were stored only as receipts. Include them
    # here as transfer-shaped records, while avoiding duplicates for new records.
    keys = {t.get("idempotency_key") for t in items if t.get("idempotency_key")}
    old_quick = await db.receipts.find({"channel": "admin_quick_recharge", "status": "active"}).sort("created_at", -1).limit(2000).to_list(2000)
    for r in old_quick:
        if r.get("idempotency_key") and r.get("idempotency_key") in keys:
            continue
        items.append({
            "id": r.get("id"), "number": r.get("number"), "idempotency_key": r.get("idempotency_key"),
            "source_type": "cash", "source_id": "cash", "source_name": "الصندوق",
            "dest_type": "customer", "dest_id": r.get("party_id"), "dest_name": r.get("party_name", ""),
            "amount": r.get("amount", 0), "description": r.get("description", ""),
            "operation_type": "quick_recharge", "channel": "admin_quick_recharge",
            "status": "active", "created_at": r.get("created_at", ""), "username": r.get("username", ""),
        })
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return [clean_doc(t) for t in items[:2000]]


# ================= CUSTOM ACCOUNT TYPES =================
class AccountTypeIn(BaseModel):
    name: str
    base_type: str = "customer"  # customer / pos / supplier / expense
    active: bool = True


@api.get("/account-types")
async def list_account_types(user=Depends(get_current_user)):
    items = await db.account_types.find({"active": {"$ne": False}}).sort("created_at", 1).to_list(500)
    return [clean_doc(x) for x in items]


@api.post("/account-types")
async def create_account_type(data: AccountTypeIn, user=Depends(require_perm("receipts"))):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="أدخل اسم نوع الحساب")
    if data.base_type not in ("customer", "pos", "supplier", "expense"):
        raise HTTPException(status_code=400, detail="قاعدة الحساب غير صحيحة")
    if await db.account_types.find_one({"name": name, "active": {"$ne": False}}):
        raise HTTPException(status_code=400, detail="يوجد نوع حساب بنفس الاسم")
    doc = {"id": str(uuid.uuid4()), "name": name, "base_type": data.base_type, "active": True, "created_at": now_iso(), "created_by": user.get("username")}
    await db.account_types.insert_one(doc)
    await audit_log(user, "create", "account_type", doc["id"], None, {"name": name, "base_type": data.base_type})
    return clean_doc(doc)


@api.put("/account-types/{type_id}")
async def update_account_type(type_id: str, data: AccountTypeIn, user=Depends(require_perm("receipts"))):
    name = (data.name or "").strip()
    if not name or data.base_type not in ("customer", "pos", "supplier", "expense"):
        raise HTTPException(status_code=400, detail="بيانات نوع الحساب غير صحيحة")
    current = await db.account_types.find_one({"id": type_id, "active": {"$ne": False}})
    if not current:
        raise HTTPException(status_code=404, detail="نوع الحساب غير موجود")
    duplicate = await db.account_types.find_one({"id": {"$ne": type_id}, "name": name, "active": {"$ne": False}})
    if duplicate:
        raise HTTPException(status_code=400, detail="يوجد نوع حساب بنفس الاسم")
    usage = sum([
        await db.customers.count_documents({"account_type": type_id}),
        await db.suppliers.count_documents({"account_type": type_id}),
        await db.expense_accounts.count_documents({"account_type": type_id}),
    ])
    if usage and data.base_type != current.get("base_type"):
        raise HTTPException(status_code=409, detail="لا يمكن تغيير القاعدة التشغيلية لنوع مرتبط بحسابات؛ عدّل الاسم فقط")
    r = await db.account_types.update_one({"id": type_id, "active": {"$ne": False}}, {"$set": {"name": name, "base_type": data.base_type}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="نوع الحساب غير موجود")
    await audit_log(user, "update", "account_type", type_id, None, {"name": name, "base_type": data.base_type})
    return {"ok": True}


@api.delete("/account-types/{type_id}")
async def delete_account_type(type_id: str, user=Depends(require_perm("receipts"))):
    """Soft-delete an unused custom type; never delete or reclassify financial accounts."""
    current = await db.account_types.find_one({"id": type_id, "active": {"$ne": False}})
    if not current:
        raise HTTPException(status_code=404, detail="نوع الحساب غير موجود")
    usage = sum([
        await db.customers.count_documents({"account_type": type_id}),
        await db.suppliers.count_documents({"account_type": type_id}),
        await db.expense_accounts.count_documents({"account_type": type_id}),
    ])
    if usage:
        raise HTTPException(status_code=409, detail=f"لا يمكن حذف النوع لأنه مرتبط بـ {usage} حساب؛ افصل الحسابات أو عطّلها أولاً")
    await db.account_types.update_one({"id": type_id}, {"$set": {"active": False, "deleted_at": now_iso(), "deleted_by": user.get("username")}})
    await audit_log(user, "delete", "account_type", type_id, None, {"name": current.get("name"), "base_type": current.get("base_type")})
    return {"ok": True}


# ================= UNIFIED ACCOUNTS =================
# ================= CUSTOM ACCOUNT LISTS (قوائم حسابات مخصصة) =================
class AccountListIn(BaseModel):
    name: str

class MoveAccountIn(BaseModel):
    list_id: Optional[str] = None

@api.get("/account-lists")
async def list_account_lists(user=Depends(get_current_user)):
    items = await db.account_lists.find().sort("created_at", 1).to_list(500)
    return [clean_doc(l) for l in items]

@api.post("/account-lists")
async def create_account_list(data: AccountListIn, user=Depends(require_perm("receipts"))):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="أدخل اسم القائمة")
    if await db.account_lists.find_one({"name": name}):
        raise HTTPException(status_code=400, detail="يوجد قائمة بنفس الاسم")
    doc = {"id": str(uuid.uuid4()), "name": name, "created_at": now_iso()}
    await db.account_lists.insert_one(doc)
    await audit_log(user, "create", "account_list", doc["id"])
    return clean_doc(doc)

@api.delete("/account-lists/{lid}")
async def delete_account_list(lid: str, user=Depends(require_perm("receipts"))):
    """Remove a list. Accounts are only DETACHED (list_id cleared) — no account/data is deleted."""
    await db.customers.update_many({"list_id": lid}, {"$set": {"list_id": None}})
    await db.suppliers.update_many({"list_id": lid}, {"$set": {"list_id": None}})
    await db.expense_accounts.update_many({"list_id": lid}, {"$set": {"list_id": None}})
    await db.account_lists.delete_one({"id": lid})
    await audit_log(user, "delete", "account_list", lid)
    return {"ok": True}

@api.put("/accounts/{ptype}/{pid}/list")
async def move_account_to_list(ptype: str, pid: str, data: MoveAccountIn, user=Depends(require_perm("receipts"))):
    """Move an existing account to a custom list by ONLY updating its list_id field.
    No new account is created and no ledger/invoice/receipt/balance is touched."""
    base_type = ptype
    if ptype not in ("customer", "pos", "supplier", "expense", "cash"):
        custom_type = await db.account_types.find_one({"id": ptype, "active": {"$ne": False}})
        if not custom_type:
            raise HTTPException(status_code=400, detail="نوع حساب غير صالح")
        base_type = custom_type.get("base_type", "customer")
    coll = db.customers if base_type in ("customer", "pos") else db.suppliers if base_type == "supplier" else db.expense_accounts if base_type == "expense" else None
    if coll is None:
        raise HTTPException(status_code=400, detail="نوع حساب غير صالح")
    lid = data.list_id or None
    if lid and not await db.account_lists.find_one({"id": lid}):
        raise HTTPException(status_code=404, detail="القائمة غير موجودة")
    r = await coll.update_one({"id": pid}, {"$set": {"list_id": lid}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="الحساب غير موجود")
    await audit_log(user, "move_to_list", ptype, pid, None, {"list_id": lid})
    return {"ok": True, "list_id": lid}


@api.get("/accounts")
async def list_accounts(user=Depends(get_current_user)):
    """Unified party accounts plus the virtual cashbox and linked bank cashboxes."""
    out: List[Dict[str, Any]] = []
    lists = await db.account_lists.find().to_list(500)
    lists_map = {l["id"]: l.get("name") for l in lists}
    # آخر تسديد لكل حساب: أحدث سند قبض/صرف فعّال، يُستخدم لترتيب الحسابات
    # حسب آخر تسديد ولعرضه في الكشف. لا يغيّر أي رصيد ولا ينشئ أي حركة.
    last_pay_map: Dict[str, Dict[str, Any]] = {}
    pay_pipeline = [
        {"$match": {"status": "active"}},
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": {"t": "$party_type", "i": "$party_id"},
                    "created_at": {"$first": "$created_at"},
                    "amount": {"$first": "$amount"},
                    "number": {"$first": "$number"},
                    "kind": {"$first": "$kind"}}},
    ]
    async for row in db.receipts.aggregate(pay_pipeline):
        key = row.get("_id") or {}
        party_id = key.get("i")
        if not party_id:
            continue
        last_pay_map["%s:%s" % (key.get("t") or "customer", party_id)] = {
            "last_payment_at": row.get("created_at"),
            "last_payment_amount": row.get("amount", 0),
            "last_payment_number": row.get("number") or "",
            "last_payment_kind": row.get("kind") or "receipt",
        }
    # تُعرض جميع الحسابات، والحسابات قيد التوثيق تظهر بنوع منفصل «عملاء غير موثقين»
    cust = await db.customers.find().to_list(10000)
    for c in cust:
        c = clean_doc(c)
        custom = await db.account_types.find_one({"id": c.get("account_type"), "active": {"$ne": False}}) if c.get("account_type") else None
        operational_type = ("pos" if c.get("customer_type") == "pos" else "customer")
        # الحسابات قيد التوثيق: نوع منفصل باسم «عملاء غير موثقين»
        if c.get("verified") is False:
            operational_type = "unverified"
            custom = None
        last_pay = last_pay_map.get("customer:" + c["id"]) or {}
        out.append({
            "id": c["id"], "type": custom.get("id") if custom else operational_type,
            "base_type": custom.get("base_type") if custom else operational_type,
            "type_name": custom.get("name") if custom else ("نقطة بيع" if operational_type == "pos" else "عميل"),
            "name": c.get("name", ""), "phone": c.get("phone", "") or "",
            "balance": c.get("balance", 0), "opening_balance": c.get("opening_balance", 0),
            "credit_limit": c.get("credit_limit", 0),
            "list_id": c.get("list_id"), "list_name": lists_map.get(c.get("list_id")),
            "status": c.get("status","active"),
            "last_payment_at": last_pay.get("last_payment_at"),
            "last_payment_amount": last_pay.get("last_payment_amount", 0),
            "last_payment_number": last_pay.get("last_payment_number", ""),
            "last_payment_kind": last_pay.get("last_payment_kind", ""),
        })
    sup = await db.suppliers.find().to_list(10000)
    for s in sup:
        s = clean_doc(s)
        custom = await db.account_types.find_one({"id": s.get("account_type"), "active": {"$ne": False}}) if s.get("account_type") else None
        last_pay = last_pay_map.get("supplier:" + s["id"]) or {}
        out.append({
            "id": s["id"], "type": custom.get("id") if custom else "supplier",
            "base_type": custom.get("base_type") if custom else "supplier",
            "type_name": custom.get("name") if custom else "مورد",
            "name": s.get("name", ""), "phone": s.get("phone", "") or "",
            "balance": s.get("balance", 0), "opening_balance": s.get("opening_balance", 0),
            "credit_limit": s.get("credit_limit", 0),
            "list_id": s.get("list_id"), "list_name": lists_map.get(s.get("list_id")),
            "status": s.get("status","active"),
            "last_payment_at": last_pay.get("last_payment_at"),
            "last_payment_amount": last_pay.get("last_payment_amount", 0),
            "last_payment_number": last_pay.get("last_payment_number", ""),
            "last_payment_kind": last_pay.get("last_payment_kind", ""),
        })
    accs = await db.expense_accounts.find().to_list(500)
    # expense accounts don't hold balances but we surface total spent
    for a in accs:
        a = clean_doc(a)
        custom = await db.account_types.find_one({"id": a.get("account_type"), "active": {"$ne": False}}) if a.get("account_type") else None
        spent_docs = await db.expenses.find({"account_id": a["id"], "status": "active"}).to_list(20000)
        transfer_docs = await db.transfers.find({
            "dest_type": "expense", "dest_id": a["id"], "status": {"$in": ["active", "done"]}
        }).to_list(20000)
        spent = sum(x.get("amount", 0) for x in spent_docs) + sum(x.get("amount", 0) for x in transfer_docs)
        out.append({
            "id": a["id"], "type": custom.get("id") if custom else "expense",
            "base_type": custom.get("base_type") if custom else "expense",
            "type_name": custom.get("name") if custom else "حساب مصروفات",
            "name": a.get("name", ""), "phone": "",
            "balance": -spent, "opening_balance": 0,
            "credit_limit": 0,
            "list_id": a.get("list_id"), "list_name": lists_map.get(a.get("list_id")),
            "status": "active",
        })
    # Cash summary as a virtual account; linked bank/wallet cashboxes are
    # separate accounts and must not be counted a second time here.
    cash_all = 0.0
    sales = [s for s in await db.sales.find({"status": "active", "sale_type": "cash"}).to_list(20000) if not s.get("cashbox_id")]
    purchases = await db.purchases.find({"status": "active", "purchase_type": "cash"}).to_list(20000)
    recs = [r for r in await db.receipts.find({"status": "active"}).to_list(20000) if not r.get("cashbox_id")]
    exps = await db.expenses.find({"status": "active"}).to_list(20000)
    trs = await db.transfers.find({"status": "active"}).to_list(20000)
    cash_all = (sum(s.get("total",0) for s in sales)
                - sum(p.get("total",0) for p in purchases)
                + sum(r.get("amount",0) for r in recs if r.get("kind")=="receipt")
                + sum(t.get("amount",0) for t in trs if t.get("dest_type")=="cash")
                - sum(r.get("amount",0) for r in recs if r.get("kind")=="payment")
                - sum(e.get("amount",0) for e in exps)
                - sum(t.get("amount",0) for t in trs if t.get("source_type")=="cash"))
    out.insert(0, {"id": "cash", "type": "cash", "name": "الصندوق", "phone": "",
                   "balance": cash_all, "opening_balance": 0, "credit_limit": 0, "status": "active"})
    for cashbox in await db.cashboxes.find().sort("created_at", 1).to_list(1000):
        cashbox_balance = await _cashbox_balance(cashbox.get("id"))
        out.append({
            "id": cashbox.get("id"), "type": "cashbox", "base_type": "cashbox",
            "type_name": "صندوق مرتبط", "name": cashbox.get("name") or "صندوق مرتبط",
            "phone": cashbox.get("account_number") or "", "balance": cashbox_balance,
            "opening_balance": 0, "credit_limit": 0, "status": "active" if cashbox.get("active", True) else "disabled",
            "bank_account_id": cashbox.get("bank_account_id"), "provider_type": cashbox.get("provider_type"),
        })
    return out


# ================= OPENING BALANCES REPORT =================
@api.get("/reports/opening-balances")
async def report_opening_balances(user=Depends(require_perm("reports"))):
    rows: List[Dict[str, Any]] = []
    for c in await db.customers.find({"opening_balance": {"$ne": 0}}).to_list(10000):
        c = clean_doc(c)
        rows.append({
            "id": c["id"], "type": ("pos" if c.get("customer_type") == "pos" else "customer"),
            "name": c.get("name", ""), "phone": c.get("phone", "") or "",
            "opening_balance": c.get("opening_balance", 0),
            "current_balance": c.get("balance", 0),
        })
    for s in await db.suppliers.find({"opening_balance": {"$ne": 0}}).to_list(10000):
        s = clean_doc(s)
        rows.append({
            "id": s["id"], "type": "supplier",
            "name": s.get("name", ""), "phone": s.get("phone", "") or "",
            "opening_balance": s.get("opening_balance", 0),
            "current_balance": s.get("balance", 0),
        })
    return rows


# ================= ITEM MOVEMENT REPORT =================
@api.get("/reports/item-movement")
async def report_item_movement(
    category_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    user=Depends(require_perm("reports")),
):
    """Return every inventory movement for a category, sorted chronologically,
    with running balance (available stock = numbered available + qty available - qty sold).
    Movements: purchases (+), sales (-), card additions (+)."""
    cat = await db.card_categories.find_one({"id": category_id})
    if not cat: raise HTTPException(status_code=404, detail="الفئة غير موجودة")

    if is_balance_category(cat):
        entries: List[Dict[str, Any]] = []
        async for op in db.stock_ops.find({"category_id": category_id}):
            entries.append({"created_at": op.get("created_at", ""), "type": op.get("kind", "balance"), "number": op.get("number", ""), "description": op.get("description") or "حركة مخزون رصيد", "in": _safe_amount(op.get("amount", op.get("quantity", 0))) if op.get("kind") == "balance_add" else 0, "out": _safe_amount(op.get("amount", op.get("quantity", 0))) if op.get("kind") == "balance_transfer_out" else 0})
        entries.sort(key=lambda x: parse_timestamp_utc(x.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
        running = 0.0
        filtered = []
        for entry in entries:
            running += entry["in"] - entry["out"]
            entry["balance"] = running
            if not (start or end) or timestamp_in_business_range(entry.get("created_at"), start, end):
                filtered.append(entry)
        return {"category": {"id": category_id, "name": cat.get("name", BALANCE_CATEGORY_NAME), "kind": "balance"}, "range": {"start": start, "end": end}, "balance_before": running - sum(x["in"] - x["out"] for x in filtered), "balance_after": running, "total_in": sum(x["in"] for x in filtered), "total_out": sum(x["out"] for x in filtered), "entries": filtered}

    entries: List[Dict[str, Any]] = []
    # 1) Purchases (+)
    async for p in db.purchases.find({"status": "active"}):
        for it in p.get("items", []):
            if it.get("category_id") == category_id:
                entries.append({
                    "created_at": p.get("created_at",""),
                    "type": "purchase", "number": p.get("number",""),
                    "description": f"شراء من {p.get('supplier_name','')}",
                    "in": it.get("quantity", 0), "out": 0,
                })
    # 2) Sales (-)
    async for s in db.sales.find({"status": "active"}):
        for it in s.get("items", []):
            if it.get("category_id") == category_id:
                entries.append({
                    "created_at": s.get("created_at",""),
                    "type": "sale", "number": s.get("number",""),
                    "description": f"مبيعات — {s.get('customer_name','') or 'نقدي'}",
                    "in": 0, "out": it.get("quantity", 0),
                })
    # 3) Direct card additions (numbered + quantity) — count as "in"
    async for op in db.stock_ops.find({"category_id": category_id}):
        entries.append({
            "created_at": op.get("created_at",""),
            "type": op.get("kind","add"), "number": "-",
            "description": op.get("description") or "إضافة مخزون بدون فاتورة",
            "in": op.get("quantity", 0), "out": 0,
        })
    # 4) Legacy cards without stock_ops entry — one row per legacy insert date
    # Detect legacy numbered cards not covered by stock_ops (cards created before we started logging)
    logged_dates = set()
    async for op in db.stock_ops.find({"category_id": category_id, "kind": "add_numbered"}):
        logged_dates.add(op.get("created_at",""))
    legacy_by_date: Dict[str, int] = {}
    async for c in db.cards.find({"category_id": category_id}):
        ca = c.get("created_at","")
        if ca and ca not in logged_dates:
            legacy_by_date[ca] = legacy_by_date.get(ca, 0) + 1
    for dt, qty in legacy_by_date.items():
        entries.append({
            "created_at": dt, "type": "add_numbered_legacy", "number": "-",
            "description": f"إضافة {qty} كرت مرقم (سجل سابق)",
            "in": qty, "out": 0,
        })

    entries.sort(key=lambda x: parse_timestamp_utc(x.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
    running = 0.0
    filtered: List[Dict[str, Any]] = []
    for e in entries:
        # opening (before window) accumulates but is not shown
        running += (e["in"] or 0) - (e["out"] or 0)
        e["balance"] = running
        if (start or end) and not timestamp_in_business_range(e.get("created_at"), start, end): continue
        filtered.append(e)

    # Balance BEFORE window
    balance_before = 0.0
    if start:
        start_utc, _ = business_range_bounds(start, None)
        for e in entries:
            entry_time = parse_timestamp_utc(e.get("created_at"))
            if entry_time and start_utc and entry_time < start_utc:
                balance_before += (e["in"] or 0) - (e["out"] or 0)

    total_in = sum(e["in"] for e in filtered)
    total_out = sum(e["out"] for e in filtered)
    return {
        "category": {"id": category_id, "name": cat.get("name", "")},
        "range": {"start": start, "end": end},
        "balance_before": balance_before,
        "balance_after": running,
        "total_in": total_in, "total_out": total_out,
        "entries": filtered,
    }


# ================= CURRENCIES =================
class CurrencyIn(BaseModel):
    name: str
    symbol: str
    rate_to_yer: float  # 1 unit of this currency = X YER
    active: Optional[bool] = True

@api.get("/currencies")
async def list_currencies(user=Depends(get_current_user)):
    items = await db.currencies.find().to_list(200)
    return [clean_doc(c) for c in items]

@api.post("/currencies")
async def create_currency(data: CurrencyIn, user=Depends(require_perm("settings"))):
    if data.rate_to_yer <= 0:
        raise HTTPException(status_code=400, detail="سعر الصرف غير صالح")
    dup = await db.currencies.find_one({"symbol": data.symbol})
    if dup: raise HTTPException(status_code=400, detail="العملة موجودة مسبقاً")
    doc = {
        "id": str(uuid.uuid4()), "name": data.name.strip(),
        "symbol": data.symbol.strip(), "rate_to_yer": float(data.rate_to_yer),
        "active": bool(data.active), "created_at": now_iso(),
        "user_id": user["id"],
    }
    await db.currencies.insert_one(doc)
    return clean_doc(doc)

@api.put("/currencies/{cid}")
async def update_currency(cid: str, data: CurrencyIn, user=Depends(require_perm("settings"))):
    if data.rate_to_yer <= 0:
        raise HTTPException(status_code=400, detail="سعر الصرف غير صالح")
    await db.currencies.update_one({"id": cid}, {"$set": {
        "name": data.name.strip(), "symbol": data.symbol.strip(),
        "rate_to_yer": float(data.rate_to_yer), "active": bool(data.active),
        "updated_at": now_iso(),
    }})
    return clean_doc(await db.currencies.find_one({"id": cid}))

@api.delete("/currencies/{cid}")
async def delete_currency(cid: str, user=Depends(require_perm("settings"))):
    cur = await db.currencies.find_one({"id": cid})
    if not cur: raise HTTPException(status_code=404, detail="العملة غير موجودة")
    # Check if currency was used anywhere → soft-disable instead of hard delete
    used = (await db.sales.count_documents({"currency_symbol": cur.get("symbol")})
            + await db.purchases.count_documents({"currency_symbol": cur.get("symbol")})
            + await db.receipts.count_documents({"currency_symbol": cur.get("symbol")})
            + await db.transfers.count_documents({"currency_symbol": cur.get("symbol")})
            + await db.expenses.count_documents({"currency_symbol": cur.get("symbol")}))
    if used > 0:
        await db.currencies.update_one({"id": cid}, {"$set": {"active": False}})
        return {"ok": True, "action": "disabled", "used_in": used,
                "reason": "العملة مستخدمة في عمليات سابقة، تم تعطيلها بدلاً من الحذف"}
    await db.currencies.delete_one({"id": cid})
    return {"ok": True, "action": "deleted"}


def _safe_amount(value) -> float:
    """Normalize nullable/malformed monetary values at the API boundary."""
    try:
        if value is None or value == "":
            return 0.0
        number = float(value)
        return number if number == number else 0.0
    except (TypeError, ValueError):
        return 0.0


def _transfer_party_label(name: Any, phone: Any, fallback: str) -> str:
    name_text = str(name or "").strip()
    phone_text = str(phone or "").strip()
    if name_text and phone_text:
        return f"{name_text} — {phone_text}"
    return name_text or phone_text or fallback


def _transfer_display_title(transfer: Dict[str, Any], outgoing: bool) -> str:
    sender_label = _transfer_party_label(
        transfer.get("sender_name") or transfer.get("source_name"),
        transfer.get("sender_phone") or transfer.get("source_phone"),
        "الحساب المرسل",
    )
    recipient_label = _transfer_party_label(
        transfer.get("recipient_name") or transfer.get("dest_name"),
        transfer.get("recipient_phone") or transfer.get("dest_phone"),
        "الحساب المستلم",
    )
    return f"تحويل صادر إلى: {recipient_label}" if outgoing else f"تحويل وارد من: {sender_label}"


def _transfer_with_party_fallback(transfer: Dict[str, Any], party_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Fill only missing legacy participant fields from their stored account IDs."""
    enriched = dict(transfer or {})
    sender_id = enriched.get("sender_id") or enriched.get("source_id")
    recipient_id = enriched.get("recipient_id") or enriched.get("dest_id")
    sender = party_map.get(sender_id) or {}
    recipient = party_map.get(recipient_id) or {}
    if not enriched.get("sender_name"):
        enriched["sender_name"] = enriched.get("source_name") or sender.get("name")
    if not enriched.get("sender_phone"):
        enriched["sender_phone"] = enriched.get("source_phone") or sender.get("phone")
    if not enriched.get("recipient_name"):
        enriched["recipient_name"] = enriched.get("dest_name") or recipient.get("name")
    if not enriched.get("recipient_phone"):
        enriched["recipient_phone"] = enriched.get("dest_phone") or recipient.get("phone")
    return enriched


def _transfer_statement_details(transfer: Dict[str, Any], outgoing: bool) -> Dict[str, Any]:
    """Build a truthful, bilingual-safe statement view for a transfer.

    Subscriber transfers keep the financial ledger description for accounting,
    but the statement must expose the transfer document's real participants and
    amounts. Missing legacy fields remain None and are rendered as unavailable
    by the frontend rather than being fabricated.
    """
    transfer = transfer or {}
    operation_type = transfer.get("operation_type") or (
        "subscriber_transfer" if transfer.get("sender_id") and transfer.get("recipient_id") else "transfer"
    )
    sender_name = transfer.get("sender_name") or transfer.get("source_name")
    sender_phone = transfer.get("sender_phone") or transfer.get("source_phone")
    recipient_name = transfer.get("recipient_name") or transfer.get("dest_name")
    recipient_phone = transfer.get("recipient_phone") or transfer.get("dest_phone")
    amount = _safe_amount(transfer.get("amount"))
    commission = transfer.get("commission")
    sender_debit = transfer.get("sender_debit")
    recipient_credit = transfer.get("recipient_credit")
    note = (transfer.get("description") or "").strip()
    reference = transfer.get("reference") or transfer.get("number")
    is_subscriber = operation_type == "subscriber_transfer" or (
        transfer.get("sender_id") and transfer.get("recipient_id")
    )
    title = _transfer_display_title(transfer, outgoing)

    parts = [title, f"المبلغ: {amount:,.2f}"]
    if is_subscriber and commission is not None:
        parts.append(f"العمولة: {_safe_amount(commission):,.2f}")
    if outgoing and sender_debit is not None:
        parts.append(f"إجمالي الخصم: {_safe_amount(sender_debit):,.2f}")
    if not outgoing and recipient_credit is not None:
        parts.append(f"المبلغ المستلم: {_safe_amount(recipient_credit):,.2f}")
    if note:
        parts.append(f"البيان: {note}")

    return {
        "operation_type": operation_type,
        "direction": "outgoing" if outgoing else "incoming",
        "sender_id": transfer.get("sender_id") or transfer.get("source_id"),
        "sender_name": sender_name,
        "sender_phone": sender_phone,
        "sender_type": transfer.get("sender_type") or transfer.get("source_type"),
        "recipient_id": transfer.get("recipient_id") or transfer.get("dest_id"),
        "recipient_name": recipient_name,
        "recipient_phone": recipient_phone,
        "recipient_type": transfer.get("recipient_type") or transfer.get("dest_type"),
        "amount": amount,
        "commission": commission,
        "sender_debit": sender_debit,
        "recipient_credit": recipient_credit,
        "sender_balance_after": transfer.get("sender_balance_after"),
        "recipient_balance_after": transfer.get("recipient_balance_after"),
        "reference": reference,
        "channel": transfer.get("channel"),
        "note": note or None,
        "display_description": title,
    }


# ================= UNIFIED ACCOUNT STATEMENT =================
@api.get("/accounts/{ptype}/{pid}/statement")
async def account_statement(
    ptype: str, pid: str,
    start: Optional[str] = None, end: Optional[str] = None,
    user=Depends(get_current_user),
):
    """Statement for any party: customer / pos / supplier / expense / cash.
    Returns account metadata, entries (with running balance), and totals."""
    account: Dict[str, Any] = {}
    entries: List[Dict[str, Any]] = []
    custom_type = None
    if ptype not in ("customer", "pos", "supplier", "expense", "cash", "cashbox"):
        custom_type = await db.account_types.find_one({"id": ptype, "active": {"$ne": False}})
        if not custom_type:
            raise HTTPException(status_code=400, detail="نوع الحساب غير مدعوم")
        statement_type = custom_type.get("base_type", "customer")
    else:
        statement_type = ptype

    if statement_type in ("customer", "pos"):
        doc = await db.customers.find_one({"id": pid})
        if not doc: raise HTTPException(status_code=404, detail="الحساب غير موجود")
        operational_type = "pos" if doc.get("customer_type")=="pos" else "customer"
        account = {"id": doc["id"], "type": ptype if custom_type else operational_type,
                   "base_type": operational_type,
                   "type_name": custom_type.get("name") if custom_type else ("نقطة بيع" if operational_type == "pos" else "عميل"),
                   "name": doc.get("name", ""), "phone": doc.get("phone", "") or "",
                   "balance": doc.get("balance", 0), "opening_balance": doc.get("opening_balance", 0),
                   "credit_limit": doc.get("credit_limit", 0), "status": doc.get("status","active")}
        ledger = await db.ledger.find({"party_type": "customer", "party_id": pid}).sort("created_at", 1).to_list(20000)
        transfer_docs = await db.transfers.find({"status": {"$in": ["active", "done"]}, "$or": [{"sender_id": pid}, {"recipient_id": pid}, {"source_id": pid, "source_type": "customer"}, {"dest_id": pid, "dest_type": "customer"}]}).to_list(5000)
        party_ids = set()
        for transfer in transfer_docs:
            for key in ("sender_id", "recipient_id", "source_id", "dest_id"):
                if transfer.get(key):
                    party_ids.add(transfer[key])
        party_map: Dict[str, Dict[str, Any]] = {}
        if party_ids:
            for collection in (db.customers, db.suppliers):
                for party in await collection.find({"id": {"$in": list(party_ids)}}).to_list(len(party_ids)):
                    party_map[party.get("id")] = party
        transfer_by_number = {t.get("number"): t for t in transfer_docs if t.get("number")}
        for e in ledger:
            display_entry = _imported_ledger_display(e)
            row = {"created_at": e.get("created_at",""), "number": display_entry.get("op_number",""), "description": display_entry.get("description", ""), "debit": e.get("debit", 0), "credit": e.get("credit", 0)}
            t = transfer_by_number.get(e.get("op_number"))
            if t:
                statement_transfer = _transfer_with_party_fallback(t, party_map)
                outgoing = statement_transfer.get("sender_id") == pid or statement_transfer.get("source_id") == pid
                details = _transfer_statement_details(statement_transfer, outgoing)
                row.update({
                    "description": details["display_description"],
                    "operation_type": details["operation_type"],
                    "transfer_id": statement_transfer.get("id"),
                    "reference": details["reference"],
                    "source_id": details["sender_id"], "dest_id": details["recipient_id"],
                    "source_name": details["sender_name"], "dest_name": details["recipient_name"],
                    "source_phone": details["sender_phone"], "dest_phone": details["recipient_phone"],
                    "sender_debit": details["sender_debit"], "recipient_credit": details["recipient_credit"],
                    "counterparty_name": details["recipient_name"] if outgoing else details["sender_name"],
                    "counterparty_phone": details["recipient_phone"] if outgoing else details["sender_phone"],
                    "transfer_description": details["note"],
                    "transfer_details": details,
                })
            entries.append(row)
    elif statement_type == "supplier":
        doc = await db.suppliers.find_one({"id": pid})
        if not doc: raise HTTPException(status_code=404, detail="الحساب غير موجود")
        account = {"id": doc["id"], "type": ptype if custom_type else "supplier", "base_type": "supplier",
                   "type_name": custom_type.get("name") if custom_type else "مورد",
                   "name": doc.get("name", ""), "phone": doc.get("phone", "") or "",
                   "balance": doc.get("balance", 0), "opening_balance": doc.get("opening_balance", 0),
                   "credit_limit": doc.get("credit_limit", 0), "status": doc.get("status","active")}
        ledger = await db.ledger.find({"party_type": "supplier", "party_id": pid}).sort("created_at", 1).to_list(20000)
        for e in ledger:
            entries.append({"created_at": e.get("created_at",""), "number": e.get("op_number",""),
                            "description": e.get("description",""),
                            "debit": e.get("debit", 0), "credit": e.get("credit", 0)})
    elif statement_type == "expense":
        doc = await db.expense_accounts.find_one({"id": pid})
        if not doc: raise HTTPException(status_code=404, detail="الحساب غير موجود")
        exps = await db.expenses.find({"account_id": pid, "status": "active"}).sort("created_at", 1).to_list(20000)
        expense_transfers = await db.transfers.find({
            "dest_type": "expense", "dest_id": pid, "status": {"$in": ["active", "done"]}
        }).sort("created_at", 1).to_list(20000)
        total = sum(_safe_amount(e.get("amount")) for e in exps) + sum(_safe_amount(t.get("amount")) for t in expense_transfers)
        account = {"id": doc["id"], "type": ptype if custom_type else "expense", "base_type": "expense",
                   "type_name": custom_type.get("name") if custom_type else "حساب مصروفات", "name": doc.get("name", ""),
                   "phone": "", "balance": -total, "opening_balance": 0,
                   "credit_limit": 0, "status": "active"}
        for e in exps:
            entries.append({"created_at": e.get("created_at",""), "number": e.get("number",""),
                            "description": e.get("description") or f"مصروف {e.get('account_name','')}",
                            "debit": 0, "credit": e.get("amount", 0)})
        for t in expense_transfers:
            entries.append({"created_at": t.get("created_at", ""), "number": t.get("number", ""),
                            "description": f"سحب من {t.get('source_name', 'صندوق المحفظة')}" + (f" — {t.get('description')}" if t.get("description") else ""),
                            "debit": 0, "credit": t.get("amount", 0), "transfer_id": t.get("id")})
    elif ptype == "cashbox":
        cashbox = await db.cashboxes.find_one({"id": pid})
        if not cashbox:
            raise HTTPException(status_code=404, detail="الصندوق المرتبط غير موجود")
        direct_sales = await db.sales.find({"cashbox_id": pid, "status": "active", "sale_type": "cash"}).sort("created_at", 1).to_list(20000)
        for sale in direct_sales:
            entries.append({
                "created_at": sale.get("created_at", ""), "number": sale.get("number", ""),
                "description": f"مبيعات إلكترونية / نقدية — {sale.get('items', [{}])[0].get('category_name', '')}",
                "debit": sale.get("total", 0), "credit": 0,
                "receipt_kind": "public_direct_sale", "payment_reference": sale.get("payment_reference"),
            })
        recs = await db.receipts.find({"cashbox_id": pid, "status": "active"}).sort("created_at", 1).to_list(20000)
        for r in recs:
            incoming = r.get("kind") == "receipt"
            label = "سداد آلي" if r.get("receipt_kind") == "automatic_payment" or r.get("payment_verification_id") else ("سند قبض" if incoming else "سند صرف")
            entries.append({
                "created_at": r.get("created_at", ""), "number": r.get("number", ""),
                "description": f"{label} — {r.get('party_name', '')}" + (f" — المرجع: {r.get('payment_reference')}" if r.get("payment_reference") else ""),
                "debit": r.get("amount", 0) if incoming else 0,
                "credit": 0 if incoming else r.get("amount", 0),
                "receipt_kind": r.get("receipt_kind") or ("automatic_payment" if r.get("payment_verification_id") else r.get("kind")),
                "payment_reference": r.get("payment_reference"),
            })
        transfers = await db.transfers.find({
            "status": {"$in": ["active", "done"]},
            "$or": [
                {"source_type": "cashbox", "source_id": pid},
                {"dest_type": "cashbox", "dest_id": pid},
            ],
        }).sort("created_at", 1).to_list(20000)
        for transfer in transfers:
            incoming = transfer.get("dest_type") == "cashbox" and transfer.get("dest_id") == pid
            entries.append({
                "created_at": transfer.get("created_at", ""), "number": transfer.get("number", ""),
                "description": ("إيداع إلى صندوق المحفظة من " if incoming else "سحب من صندوق المحفظة إلى ") +
                               (transfer.get("source_name") if incoming else transfer.get("dest_name") or "الحساب المحدد"),
                "debit": transfer.get("amount", 0) if incoming else 0,
                "credit": 0 if incoming else transfer.get("amount", 0),
                "receipt_kind": "cashbox_transfer",
            })
        entries.sort(key=lambda item: parse_timestamp_utc(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
        account = {"id": cashbox["id"], "type": "cashbox", "name": cashbox.get("name", "صندوق مرتبط"),
                   "phone": cashbox.get("account_number", ""), "balance": sum(_safe_amount(e.get("debit")) - _safe_amount(e.get("credit")) for e in entries),
                   "opening_balance": 0, "credit_limit": 0, "status": "active" if cashbox.get("active", True) else "disabled",
                   "bank_account_id": cashbox.get("bank_account_id"), "provider_type": cashbox.get("provider_type")}
    elif ptype == "cash":
        # Cash box statement — mimic /cash/statement
        sales = [s for s in await db.sales.find({"status": "active", "sale_type": "cash"}).to_list(20000) if not s.get("cashbox_id")]
        purchases = await db.purchases.find({"status": "active", "purchase_type": "cash"}).to_list(20000)
        recs = [r for r in await db.receipts.find({"status": "active"}).to_list(20000) if not r.get("cashbox_id")]
        exps = await db.expenses.find({"status": "active"}).to_list(20000)
        trs = await db.transfers.find({"status": "active"}).to_list(20000)
        for s in sales:
            entries.append({"created_at": s.get("created_at",""), "number": s.get("number",""),
                            "description": f"مبيعات نقدية — {s.get('customer_name','') or 'نقدي'}",
                            "debit": s.get("total", 0), "credit": 0})
        for p in purchases:
            entries.append({"created_at": p.get("created_at",""), "number": p.get("number",""),
                            "description": f"مشتريات نقدية — {p.get('supplier_name','') or 'نقدي'}",
                            "debit": 0, "credit": p.get("total", 0)})
        for r in recs:
            if r.get("kind") == "receipt":
                entries.append({"created_at": r.get("created_at",""), "number": r.get("number",""),
                                "description": f"سند قبض — {r.get('party_name','')}",
                                "debit": r.get("amount",0), "credit": 0})
            else:
                entries.append({"created_at": r.get("created_at",""), "number": r.get("number",""),
                                "description": f"سند صرف — {r.get('party_name','')}",
                                "debit": 0, "credit": r.get("amount",0)})
        for e in exps:
            entries.append({"created_at": e.get("created_at",""), "number": e.get("number",""),
                            "description": f"مصروف — {e.get('account_name','')}" + (f" — {e.get('description')}" if e.get('description') else ""),
                            "debit": 0, "credit": e.get("amount",0)})
        for t in trs:
            if t.get("dest_type") == "cash":
                entries.append({"created_at": t.get("created_at",""), "number": t.get("number",""),
                                "description": f"تحويل من {t.get('source_name','')}",
                                "debit": t.get("amount",0), "credit": 0})
            elif t.get("source_type") == "cash":
                entries.append({"created_at": t.get("created_at",""), "number": t.get("number",""),
                                "description": f"تحويل إلى {t.get('dest_name','')}",
                                "debit": 0, "credit": t.get("amount",0)})
        total_all_debit = sum(_safe_amount(x.get("debit")) for x in entries)
        total_all_credit = sum(_safe_amount(x.get("credit")) for x in entries)
        account = {"id": "cash", "type": "cash", "name": "الصندوق", "phone": "",
                   "balance": total_all_debit - total_all_credit, "opening_balance": 0,
                   "credit_limit": 0, "status": "active"}
    else:
        raise HTTPException(status_code=400, detail="نوع الحساب غير مدعوم")

    # Normalize every record before sorting, filtering, totaling, or rendering.
    # A single null/malformed amount must never abort the whole statement.
    for e in entries:
        e["created_at"] = e.get("created_at") or ""
        e["description"] = e.get("description") or ""
        e["debit"] = _safe_amount(e.get("debit"))
        e["credit"] = _safe_amount(e.get("credit"))

    entries.sort(key=lambda x: parse_timestamp_utc(x.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
    # Compute running balance for ALL entries first
    running = 0.0
    for e in entries:
        running += e.get("debit", 0) - e.get("credit", 0)
        e["balance"] = running

    # Balance BEFORE filter window
    balance_before = 0.0
    if start:
        start_utc, _ = business_range_bounds(start, None)
        for e in entries:
            entry_time = parse_timestamp_utc(e.get("created_at"))
            if entry_time and start_utc and entry_time < start_utc:
                balance_before += e.get("debit", 0) - e.get("credit", 0)

    filtered: List[Dict[str, Any]] = []
    for e in entries:
        if (start or end) and not timestamp_in_business_range(e.get("created_at"), start, end): continue
        filtered.append(e)

    total_debit = sum(e["debit"] for e in filtered)
    total_credit = sum(e["credit"] for e in filtered)
    return {
        "account": account,
        "range": {"start": start, "end": end},
        "balance_before": balance_before,
        "balance_after": running,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "entries": filtered,
    }


# ================= FREE CARDS (gift card delivery) =================
FREE_CARD_STATUS = "free"
FREE_CARD_STATUS_LABEL = "مجاني"
FREE_CARD_METHODS = ("in_app", "sms", "whatsapp")
FREE_CARD_METHOD_LABELS = {"in_app": "إشعار في نافذة الحساب", "sms": "رسالة نصية", "whatsapp": "رسالة واتساب"}


def _free_card_amount(category: Optional[Dict[str, Any]]) -> float:
    """Value of the card handed out (card value, falling back to its sale price)."""
    category = category or {}
    return round(_numeric_amount(category.get("value"), 0.0) or _numeric_amount(category.get("sale_price"), 0.0), 2)


def _free_card_admin_text(send: Dict[str, Any], amount: float = 0.0) -> str:
    """One-line summary shown to the admins when a free card is handed out."""
    send = send or {}
    recipient = send.get("recipient_name") or send.get("recipient_phone") or "مستلم"
    parts = [f"تم إرسال كرت {send.get('category_name') or ''} رقم {send.get('card_number') or ''} إلى {recipient}".strip()]
    channel = FREE_CARD_METHOD_LABELS.get(str(send.get("method") or "").lower())
    if channel:
        parts.append(f"عبر {channel}")
    if send.get("username"):
        parts.append(f"بواسطة {send.get('username')}")
    text = " — ".join(parts)
    if amount:
        text += f" — القيمة: {amount:,.2f}"
    return text

class FreeCardSendIn(BaseModel):
    category_id: str
    card_id: Optional[str] = None
    card_number: Optional[str] = None
    recipient_type: str = "customer"          # customer | manual
    customer_id: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_phone: Optional[str] = None
    method: str = "in_app"                     # in_app | sms | whatsapp
    message: Optional[str] = ""
    date: Optional[str] = None
    idempotency_key: Optional[str] = None

def _clean_phone(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+").strip()

async def _free_card_template_message(category_name: str, card_number: str, recipient_name: str) -> str:
    settings = await db.settings.find_one({"key": "app_settings"}) or {}
    company = str(settings.get("company_name") or settings.get("app_name") or "شبكة جواد نت اللاسلكية").strip()
    text = await _render_message_template("free_card_send", {
        "name": recipient_name or "عميلنا",
        "category": category_name or "",
        "card_number": card_number or "",
        "company": company,
    })
    if not text:
        text = f"كرت مجاني: {category_name}\nرقم الكرت: {card_number}\nمن {company}"
    return text

@api.get("/free-cards/categories")
async def free_card_categories(user=Depends(require_perm("free_cards", "cards"))):
    """Card categories with their currently available numbered cards."""
    cats = await db.card_categories.find().sort("name", 1).to_list(500)
    result = []
    for cat in cats:
        cat = clean_doc(cat)
        if is_balance_category(cat):
            continue
        available = await db.cards.count_documents({"category_id": cat["id"], "status": "available"})
        free = await db.cards.count_documents({"category_id": cat["id"], "status": FREE_CARD_STATUS})
        sent = await db.free_card_sends.count_documents({"category_id": cat["id"]})
        result.append({
            "id": cat["id"],
            "name": cat.get("name") or "",
            "kind": cat.get("kind", "card"),
            "available": available,
            "free": free,
            "sent": sent,
        })
    return result

@api.get("/free-cards/available")
async def free_cards_available(category_id: str, q: Optional[str] = None, limit: int = 300, user=Depends(require_perm("free_cards", "cards"))):
    cat = await db.card_categories.find_one({"id": category_id})
    if not cat:
        raise HTTPException(status_code=404, detail="الفئة غير موجودة")
    if is_balance_category(cat):
        raise HTTPException(status_code=400, detail="فئة رصيد مالية وليست فئة كروت")
    query: Dict[str, Any] = {"category_id": category_id, "status": "available"}
    term = (q or "").strip()
    if term:
        query["number"] = {"$regex": _re.escape(term), "$options": "i"}
    total = await db.cards.count_documents({"category_id": category_id, "status": "available"})
    limit = min(max(int(limit or 300), 1), 1000)
    items = await db.cards.find(query).sort("created_at", 1).limit(limit).to_list(limit)
    return {
        "category_id": category_id,
        "category_name": cat.get("name") or "",
        "available": total,
        "cards": [{"id": c.get("id"), "number": c.get("number"), "created_at": c.get("created_at")} for c in items],
    }

@api.post("/free-cards/send")
@idempotent_operation("free_card_send", "free_card_sends")
async def send_free_card(data: FreeCardSendIn, user=Depends(require_perm("free_cards", "cards"))):
    method = (data.method or "in_app").strip().lower()
    if method not in FREE_CARD_METHODS:
        raise HTTPException(status_code=400, detail="طريقة الإرسال غير مدعومة")
    cat = await db.card_categories.find_one({"id": data.category_id})
    if not cat:
        raise HTTPException(status_code=404, detail="الفئة غير موجودة")
    if is_balance_category(cat):
        raise HTTPException(status_code=400, detail="فئة رصيد مالية وليست فئة كروت")
    recipient_type = (data.recipient_type or "customer").strip().lower()
    if recipient_type not in ("customer", "manual"):
        raise HTTPException(status_code=400, detail="نوع المستلم غير مدعوم")
    customer = None
    if data.customer_id:
        customer = await db.customers.find_one({"id": data.customer_id})
        if not customer:
            raise HTTPException(status_code=404, detail="حساب المستلم غير موجود")
        recipient_type = "customer"
    recipient_name = (data.recipient_name or (customer or {}).get("name") or "").strip()
    recipient_phone = _clean_phone(data.recipient_phone or (customer or {}).get("phone") or "")
    if recipient_type == "customer" and not customer:
        raise HTTPException(status_code=400, detail="اختر حساب المستلم")
    if recipient_type == "manual" and not (recipient_name or recipient_phone):
        raise HTTPException(status_code=400, detail="أدخل اسم المستلم أو رقم هاتفه")
    when = business_timestamp(data.date) if (data.date or "").strip() else now_iso()
    # Claim one available card atomically so two operators can never send the same card.
    card_query: Dict[str, Any] = {"category_id": data.category_id, "status": "available"}
    if data.card_id:
        card_query["id"] = data.card_id
    elif (data.card_number or "").strip():
        card_query["number"] = data.card_number.strip()
    card = await db.cards.find_one_and_update(
        card_query,
        {"$set": {
            "status": FREE_CARD_STATUS,
            "free_sent_at": when,
            "free_sent_by": user.get("username"),
            "updated_at": now_iso(),
        }},
    )
    if not card:
        detail = "رقم الكرت غير متاح في هذه الفئة" if (data.card_id or (data.card_number or "").strip()) else "لا يوجد كرت متاح في هذه الفئة"
        raise HTTPException(status_code=400, detail=detail)
    card = clean_doc(card)
    message = (data.message or "").strip() or await _free_card_template_message(cat.get("name") or "", card.get("number") or "", recipient_name)
    doc = {
        "id": str(uuid.uuid4()),
        "number": await next_gwd_number(),
        "category_id": cat.get("id"),
        "category_name": cat.get("name") or "",
        "card_id": card.get("id"),
        "card_number": card.get("number"),
        "recipient_type": recipient_type,
        "customer_id": (customer or {}).get("id"),
        "recipient_name": recipient_name,
        "recipient_phone": recipient_phone,
        "method": method,
        "message": message,
        "status": "sent",
        "card_status": FREE_CARD_STATUS,
        "user_id": user.get("id"),
        "username": user.get("username"),
        "idempotency_key": (data.idempotency_key or "").strip(),
        "created_at": when,
    }
    await db.free_card_sends.insert_one(doc)
    if customer and customer.get("id"):
        try:
            await notify_customer_account(customer["id"], "وصلك كرت",
                (f"من: {user.get('username','')} — الفئة: {cat.get('name','')} — رقم الكرت: {card.get('number','')}"),
                "success", {
                    "category": "card_received", "card_numbers": [str(card.get("number") or "")],
                    "category_name": cat.get("name") or "", "unit_price": 0, "total": 0, "quantity": 1,
                    "sender_name": user.get("username") or "", "sender_phone": "",
                    "send_number": doc.get("number"), "free": True, "popup": True,
                })
        except Exception:
            pass
    await log_card_event(card.get("id"), "free_send", card.get("number"), user.get("username"),
                         {"send_id": doc["id"], "send_number": doc["number"], "recipient": recipient_name,
                          "recipient_phone": recipient_phone, "method": method},
                         f"أُرسل ككرت مجاني إلى {recipient_name or recipient_phone or ''}")
    try:
        card_amount = _free_card_amount(cat)
        await notify(
            f"كرت مجاني {doc['number']}",
            _free_card_admin_text(doc, card_amount),
            "info",
            details={
                "operation": "free_card",
                "operation_id": doc["id"],
                "send_id": doc["id"],
                "number": doc["number"],
                "category_id": doc.get("category_id"),
                "category_name": doc.get("category_name"),
                "card_number": doc.get("card_number"),
                "recipient_name": recipient_name,
                "recipient_phone": recipient_phone,
                "method": method,
                "username": doc.get("username"),
                "amount": card_amount,
                "created_at": when,
            },
        )
    except Exception as exc:
        logger.warning("free card admin notification failed: %s", exc)
    in_app_created = False
    if customer and await _message_channel_enabled("free_card_send", "in_app"):
        await notify_customer_account(
            customer.get("id"),
            f"كرت مجاني — {cat.get('name') or ''}".strip(),
            message,
            "success",
            {
                "operation": "free_card",
                "operation_id": doc["id"],
                "card_number": card.get("number"),
                "category_name": cat.get("name") or "",
                "method": method,
                "customer_id": customer.get("id"),
                "send_number": doc["number"],
            },
        )
        in_app_created = True
    from urllib.parse import quote
    whatsapp_url = ""
    if recipient_phone and await _message_channel_enabled("free_card_send", "whatsapp"):
        whatsapp_url = f"https://wa.me/{recipient_phone.lstrip('+')}?text={quote(message)}"
    sms_phone = recipient_phone
    await audit_log(user, "send", "free_card", doc["id"], None, {
        "number": doc["number"],
        "card_number": card.get("number"),
        "category_id": cat.get("id"),
        "method": method,
        "recipient": recipient_name or recipient_phone,
        "customer_id": doc.get("customer_id"),
    })
    return {
        "ok": True,
        "send": clean_doc(doc),
        "message": message,
        "whatsapp_url": whatsapp_url if method == "whatsapp" else "",
        "sms_phone": sms_phone if method == "sms" else "",
        "in_app_created": in_app_created,
        "card_status": FREE_CARD_STATUS,
        "card_status_label": FREE_CARD_STATUS_LABEL,
    }

@api.get("/free-cards/sends/{send_id}")
async def free_card_send_detail(send_id: str, user=Depends(require_perm("free_cards", "cards"))):
    send = await db.free_card_sends.find_one({"id": send_id})
    if not send:
        raise HTTPException(status_code=404, detail="عملية الإرسال غير موجودة")
    send = clean_doc(send)
    cat = await db.card_categories.find_one(
        {"id": send.get("category_id")}, {"id": 1, "value": 1, "sale_price": 1}
    )
    send["amount"] = _free_card_amount(cat)
    send["channel_label"] = FREE_CARD_METHOD_LABELS.get(str(send.get("method") or "").lower(), send.get("method") or "")
    return send


@api.get("/free-cards/archive")
async def free_cards_archive(start: Optional[str] = None, end: Optional[str] = None, q: Optional[str] = None,
                             method: Optional[str] = None, category_id: Optional[str] = None,
                             limit: int = 500, user=Depends(require_perm("free_cards", "cards"))):
    query: Dict[str, Any] = {}
    if method:
        query["method"] = method
    if category_id:
        query["category_id"] = category_id
    term = (q or "").strip()
    if term:
        rx = {"$regex": _re.escape(term), "$options": "i"}
        query["$or"] = [{"recipient_name": rx}, {"recipient_phone": rx}, {"card_number": rx}, {"number": rx}]
    limit = min(max(int(limit or 500), 1), 3000)
    items = await db.free_card_sends.find(query).sort("created_at", -1).limit(limit).to_list(limit)
    items = [clean_doc(x) for x in items]
    if start or end:
        items = [x for x in items if timestamp_in_business_range(x.get("created_at"), start, end)]
    # value of every card handed out (card value, falling back to its sale price)
    category_ids = list({x.get("category_id") for x in items if x.get("category_id")})
    category_values: Dict[str, float] = {}
    if category_ids:
        async for cat in db.card_categories.find(
            {"id": {"$in": category_ids}}, {"id": 1, "value": 1, "sale_price": 1}
        ):
            category_values[cat.get("id")] = (
                _numeric_amount(cat.get("value"), 0.0) or _numeric_amount(cat.get("sale_price"), 0.0)
            )
    for x in items:
        x["amount"] = round(category_values.get(x.get("category_id"), 0.0), 2)
    summary = {
        "count": len(items),
        "in_app": sum(1 for x in items if x.get("method") == "in_app"),
        "sms": sum(1 for x in items if x.get("method") == "sms"),
        "whatsapp": sum(1 for x in items if x.get("method") == "whatsapp"),
        "amount": round(sum(x["amount"] for x in items), 2),
    }
    return {"items": items, "summary": summary, "range": {"start": start, "end": end}}

# ================= PAYMENT REQUESTS =================
class PaymentRequestIn(BaseModel):
    party_type: str
    party_id: str
    amount: float = Field(gt=0)
    method: Optional[str] = "sms"  # sms / whatsapp / manual
    message: Optional[str] = ""
    idempotency_key: str = Field(min_length=1, max_length=160)

@api.get("/payment-requests")
async def list_payment_requests(party_type: Optional[str] = None, party_id: Optional[str] = None, user=Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if party_type: q["party_type"] = party_type
    if party_id: q["party_id"] = party_id
    items = await db.payment_requests.find(q).sort("created_at", -1).limit(2000).to_list(2000)
    return [clean_doc(x) for x in items]

@api.post("/payment-requests")
@idempotent_operation("payment_request", "payment_requests")
async def create_payment_request(data: PaymentRequestIn, user=Depends(require_perm("receipts"))):
    if data.amount is None or data.amount <= 0:
        raise HTTPException(status_code=400, detail="المبلغ غير صالح")
    if data.party_type not in ("customer","pos","supplier"):
        raise HTTPException(status_code=400, detail="نوع الحساب غير مدعوم")
    if data.idempotency_key:
        existing = await db.payment_requests.find_one({"idempotency_key": data.idempotency_key})
        if existing: return clean_doc(existing)
    # Fetch party
    col = db.customers if data.party_type in ("customer","pos") else db.suppliers
    party = await col.find_one({"id": data.party_id})
    if not party: raise HTTPException(status_code=404, detail="الحساب غير موجود")
    doc = {
        "id": str(uuid.uuid4()),
        "number": await next_gwd_number(),
        "party_type": data.party_type, "party_id": data.party_id,
        "party_name": party.get("name", ""), "party_phone": party.get("phone", "") or "",
        "amount": float(data.amount),
        "method": data.method or "sms",
        "message": (data.message or "").strip(),
        "status": "sent",
        "user_id": user["id"], "username": user.get("username"),
        "idempotency_key": data.idempotency_key,
        "created_at": now_iso(),
    }
    # Compose message from the central template and append active payment accounts.
    balance = float(party.get("balance", 0) or 0)
    banks = await db.bank_accounts.find({"active": True, "show_in": "payment_requests"}).to_list(50)
    bank_lines = []
    if banks:
        bank_lines.append("بيانات السداد:")
        for b in banks:
            bank_lines.append("")
            bank_lines.append(f"{b.get('bank_name', '')}")
            bank_lines.append(f"اسم الحساب: {b.get('holder_name', '')}")
            bank_lines.append(f"رقم الحساب: {b.get('account_number', '')}")
            if b.get("details"): bank_lines.append(str(b.get("details")))
    rendered = await _render_message_template("payment_request", {
        "name": party.get("name", ""), "balance": f"{balance:,.0f}",
        "amount": f"{float(data.amount):,.0f}", "company": COMPANY_NAME,
        "bank_details": "\n".join(bank_lines),
    })
    header = doc["message"] or ""
    doc["message"] = ((header + "\n\n") if header else "") + rendered
    await db.payment_requests.insert_one(doc)
    await audit_log(user, "create", "payment_request", doc["id"], None, {"amount": data.amount})
    return clean_doc(doc)

@api.post("/payment-requests/{rid}/status")
async def set_payment_request_status(rid: str, new_status: str, user=Depends(require_perm("receipts"))):
    if new_status not in ("new","sent","paid","cancelled"):
        raise HTTPException(status_code=400, detail="حالة غير صحيحة")
    await db.payment_requests.update_one({"id": rid}, {"$set": {"status": new_status, "updated_at": now_iso()}})
    doc = await db.payment_requests.find_one({"id": rid})
    if not doc: raise HTTPException(status_code=404, detail="الطلب غير موجود")
    return clean_doc(doc)


# ================= YAPVS PAYMENT VERIFICATION =================
# A client submission only creates a pending verification. A signed Gateway SMS
# must match the reference, amount, and receiving account before the guarded
# helper creates one customer receipt. Client-pasted text is never sufficient.
PAYMENT_GATEWAY_HMAC_SECRET = (os.environ.get("PAYMENT_GATEWAY_HMAC_SECRET") or "").strip()
PAYMENT_GATEWAY_DEVICE_ID = (os.environ.get("PAYMENT_GATEWAY_DEVICE_ID") or "").strip()
PAYMENT_VERIFICATION_FAILED_LIMIT = 10
PAYMENT_VERIFICATION_RESPONSE_WINDOW_SECONDS = 15
PAYMENT_DETERMINISTIC_FAILURES = {
    "missing_transaction_id",
    "unclaimed_transaction",
    "bank_account_mismatch",
    "amount_mismatch",
    "recipient_account_mismatch",
}
PAYMENT_RESPONSE_TIMEOUT_REASON = "انتهت مهلة الاستجابة، أعد المحاولة."


def _payment_failure_query(customer_id: str, block: Optional[dict] = None) -> Dict[str, Any]:
    """Count only rejected attempts in the customer's current lock cycle.

    Rejected payment requests remain in history for audit.  ``failure_reset_at``
    is written when an administrator unlocks the account, so old failures do
    not immediately re-lock it on the next payment attempt.
    """
    query: Dict[str, Any] = {"customer_id": customer_id, "status": "rejected"}
    reset_at = str((block or {}).get("failure_reset_at") or "").strip()
    if reset_at:
        query["failure_counted_at"] = {"$gt": reset_at}
    return query


async def _count_payment_failures(customer_id: str, block: Optional[dict] = None) -> int:
    return await db.payment_verifications.count_documents(_payment_failure_query(customer_id, block))


async def _expire_unresolved_payment_confirmations(customer_id: Optional[str] = None, verification_id: Optional[str] = None):
    """Close only unanswered pending requests; never changes balances or receipts.

    This is deliberately separate from the SMS timestamp rule. A signed message
    received before a customer request may still be linked by
    ``_match_prior_gateway_message``; this helper only prevents the customer
    request itself from remaining pending forever when no Gateway result arrives.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=PAYMENT_VERIFICATION_RESPONSE_WINDOW_SECONDS)).isoformat()
    query: Dict[str, Any] = {"status": "pending", "created_at": {"$lte": cutoff}}
    if customer_id:
        query["customer_id"] = customer_id
    if verification_id:
        query["id"] = verification_id
    pending_docs = await db.payment_verifications.find(query).to_list(100)
    result = await db.payment_verifications.update_many(
        query,
        {"$set": {
            "status": "rejected",
            "failure_code": "gateway_response_timeout",
            "review_reason": PAYMENT_RESPONSE_TIMEOUT_REASON,
            "updated_at": now_iso(),
            "financial_effect": "none",
        }},
    )
    if result.modified_count:
        for verification in pending_docs:
            await _notify_payment_confirmation_failure(
                {**verification, "status": "rejected", "failure_code": "gateway_response_timeout", "review_reason": PAYMENT_RESPONSE_TIMEOUT_REASON},
                PAYMENT_RESPONSE_TIMEOUT_REASON,
            )
    return result.modified_count

class PublicPaymentConfirmationIn(PublicAuth):
    bank_account_id: str = Field(min_length=1, max_length=160)
    amount: float = Field(gt=0)
    # The client must select exactly one verification source. The optional
    # default keeps older clients compatible only when they already send one
    # source; requests containing both sources are rejected below.
    verification_method: Optional[Literal["reference", "sms_text"]] = None
    sms_text: str = Field(default="", max_length=5000)
    payment_reference: Optional[str] = Field(default=None, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=160)

class GatewayInboundSmsIn(BaseModel):
    bank_account_id: Optional[str] = None
    sender_id: str = Field(min_length=1, max_length=120)
    sms_text: str = Field(min_length=10, max_length=5000)
    received_at: Optional[str] = None
    subscription_id: Optional[int] = None

class PaymentVerificationReviewIn(BaseModel):
    status: Literal["approved", "manual_review", "rejected"]
    note: Optional[str] = ""

class PaymentGatewayConfigIn(BaseModel):
    # Sender IDs are owned by bank_accounts.gateway_sender_ids. Keep this
    # empty model for compatibility with old clients without another source.
    pass

class PaymentGatewayDeviceIn(BaseModel):
    device_id: str = Field(min_length=3, max_length=160)
    label: str = Field(min_length=1, max_length=160)
    note: Optional[str] = Field(default="", max_length=500)
    active: bool = True

def _normalize_gateway_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u200f", " ").replace("\u200e", " ").split()).strip()

def _gateway_digits(value: Any) -> str:
    arabic = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return _re.sub(r"\D", "", str(value or "").translate(arabic))

def _gateway_sender_key(value: Any) -> str:
    """Normalize the SMS origin consistently with the Android receiver.

    Mobile networks may include bidi marks or spaces around an alphanumeric
    sender. Those characters are not part of the sender identity and must not
    make a correctly configured wallet look unmatched.
    """
    raw = str(value or "")
    # Android/SIM gateways may wrap an alphanumeric Sender ID in bidi
    # isolates/embedding marks (for example: \u200f\u200f\u202aJaib\u202c\u200f).
    # All Unicode format characters are presentation metadata, not part of
    # the sender identity, so remove them before comparing allowlists.
    raw = "".join(ch for ch in raw if _unicodedata.category(ch) != "Cf")
    return _re.sub(r"\s+", "", raw).casefold().strip()


def _extract_jaib_gateway_fields(text: str) -> Dict[str, Any]:
    """Extract the compact Jaib recipient SMS format without treating balance as payment."""
    normalized = _normalize_gateway_text(text)
    arabic = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

    def number(pattern: str) -> Optional[float]:
        match = _re.search(pattern, normalized, flags=_re.IGNORECASE)
        if not match:
            return None
        raw = match.group(1).translate(arabic).replace(",", "").replace("،", "")
        try:
            value = float(raw)
            return value if value >= 0 else None
        except ValueError:
            return None

    reference_match = _re.search(r"(?:^|\s)م\s*[:：]\s*([0-9٠-٩]{6,32})(?![0-9٠-٩])", normalized)
    sender_match = _re.search(r"(?:^|\s)من\s*[:：-]?\s*([0-9٠-٩A-Z+\-]{3,40})", normalized, flags=_re.IGNORECASE)
    operation_match = _re.search(r"(?:اضيف|أضيف)\s*[0-9٠-٩.,،]+\s*ر\.?ي\s+([^\s]+)", normalized, flags=_re.IGNORECASE)
    amount = number(r"(?:اضيف|أضيف)\s*([0-9٠-٩][0-9٠-٩,،\.]{0,18})\s*ر\.?ي")
    balance = number(r"رص\s*[:：]\s*([0-9٠-٩][0-9٠-٩,،\.]{0,18})\s*ر\.?ي")
    return {
        "is_jaib_compact": bool(reference_match and amount is not None),
        "amount": amount,
        "balance_after": balance,
        "sender_reference": sender_match.group(1).translate(arabic) if sender_match else None,
        "transaction_id": reference_match.group(1).translate(arabic) if reference_match else None,
        "operation_type": operation_match.group(1) if operation_match else None,
    }

def _extract_gateway_transaction_candidates(text: str, excluded_values: Optional[List[str]] = None) -> List[str]:
    normalized = _normalize_gateway_text(text)
    excluded = {_gateway_digits(value) for value in (excluded_values or []) if _gateway_digits(value)}
    candidates: List[str] = []
    # Do not split the integer part of a decimal balance such as 113568.24
    # into a false transaction candidate.
    for match in _re.finditer(r"(?<![0-9٠-٩])([0-9٠-٩]{6,32})(?![0-9٠-٩.,،])", normalized):
        candidate = _gateway_digits(match.group(1))
        if not candidate or candidate in excluded:
            continue
        context = normalized[max(0, match.start() - 28):match.start()]
        if _re.search(
            r"(?:الرصيد|رصيد|balance|account|حساب|الهاتف|phone|التاريخ|date|الوقت|time)"
            r"(?:\s+(?:الإجمالي|المتبقي|المودع|المستلم|رقم))?\s*[:#-]?\s*$",
            context,
            flags=_re.IGNORECASE,
        ):
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates

def _extract_gateway_transaction_id(text: str, excluded_values: Optional[List[str]] = None) -> Optional[str]:
    normalized = _normalize_gateway_text(text)
    jaib = _extract_jaib_gateway_fields(normalized)
    if jaib.get("transaction_id"):
        return str(jaib["transaction_id"])
    patterns = (
        r"(?:transaction|reference|ref|txn|رقم العملية|رقم الحوالة|المرجع|مرجع)\s*(?:id|no|number|رقم)?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-]{4,31})",
        r"(?:عملية|حوالة)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-]{5,31})",
    )
    for pattern in patterns:
        match = _re.search(pattern, normalized, flags=_re.IGNORECASE)
        if match:
            return match.group(1).upper()
    # Conservative fallback for banks that send a numeric reference without
    # a label. Ambiguous numeric messages fail closed instead of guessing.
    candidates = _extract_gateway_transaction_candidates(normalized, excluded_values)
    if len(candidates) == 1:
        return candidates[0]
    # Conservative fallback: only long alphanumeric tokens containing a digit.
    for token in _re.findall(r"\b[A-Z0-9][A-Z0-9\-]{5,31}\b", normalized, flags=_re.IGNORECASE):
        if _re.search(r"\d", token) and not token.isdigit():
            return token.upper()
    return None

def _extract_gateway_amount(text: str) -> Optional[float]:
    normalized = _normalize_gateway_text(text)
    jaib = _extract_jaib_gateway_fields(normalized)
    if jaib.get("amount") is not None:
        return float(jaib["amount"])
    patterns = (
        r"(?:amount|المبلغ|مبلغ|received|استلمت|تم استلام)\s*[:\-]?\s*([0-9٠-٩][0-9٠-٩,،\.]{0,18})",
        r"([0-9٠-٩][0-9٠-٩,،\.]{1,12})\s*(?:YER|ريال|ر\.ي)",
    )
    for pattern in patterns:
        match = _re.search(pattern, normalized, flags=_re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")).replace(",", "").replace("،", "")
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return None

async def _gateway_sender_allowlist(bank: dict) -> List[str]:
    from_bank = bank.get("gateway_sender_ids") or []
    return sorted({_gateway_sender_key(x) for x in from_bank if _gateway_sender_key(x)})


async def _gateway_history_for_bank(transaction_id: str, bank: dict) -> List[dict]:
    """Find verified history for a bank, including safe legacy bank-ID matches.

    Bank records can be recreated while the immutable Gateway message history
    still contains the previous bank UUID. When the Sender ID is configured
    for exactly one active bank, it is a stronger routing key than that stale
    historical UUID. This fallback is deliberately limited to one unique
    active Sender-ID owner and an exact transaction reference.
    """
    bank_id = str(bank.get("id") or "").strip()
    exact = await db.payment_gateway_messages.find({
        "bank_account_id": bank_id,
        "transaction_id": transaction_id,
    }).sort("received_at_server", -1).limit(200).to_list(200)
    if exact:
        return exact

    allowlist = set(await _gateway_sender_allowlist(bank))
    if len(allowlist) != 1:
        return []
    active_banks = await db.bank_accounts.find({"active": True}, {"id": 1, "gateway_sender_ids": 1}).to_list(500)
    owners = []
    for candidate in active_banks:
        candidate_allowlist = set(await _gateway_sender_allowlist(candidate))
        if allowlist.intersection(candidate_allowlist):
            owners.append(str(candidate.get("id") or "").strip())
    if owners != [bank_id]:
        return []

    historical = await db.payment_gateway_messages.find({
        "transaction_id": transaction_id,
    }).sort("received_at_server", -1).limit(200).to_list(200)
    return [event for event in historical if _gateway_sender_key(event.get("sender_id")) in allowlist]

async def _migrate_legacy_gateway_sender_ids_to_banks() -> int:
    """Move retired settings.sender_ids into bank accounts exactly once."""
    settings = await db.settings.find_one({"key": "payment_gateway"}) or {}
    legacy = settings.get("sender_ids") or {}
    if not isinstance(legacy, dict) or not legacy:
        return 0
    migrated = 0
    for bank_id, values in legacy.items():
        cleaned = sorted({_gateway_sender_key(value) for value in (values or []) if _gateway_sender_key(value)})
        bank = await db.bank_accounts.find_one({"id": str(bank_id)})
        if not bank or not cleaned:
            continue
        existing = bank.get("gateway_sender_ids") or []
        merged = sorted({str(value).strip() for value in [*existing, *cleaned] if str(value).strip()})[:20]
        await db.bank_accounts.update_one({"id": bank["id"]}, {"$set": {"gateway_sender_ids": merged, "updated_at": now_iso()}})
        migrated += 1
    await db.settings.update_one({"key": "payment_gateway"}, {"$unset": {"sender_ids": ""}, "$set": {"sender_ids_migrated_to_bank_accounts_at": now_iso()}})
    return migrated

def _gateway_received_at(value: Optional[str]) -> datetime:
    parsed = parse_timestamp_utc(value) if value else None
    return parsed or datetime.now(timezone.utc)

def _payment_amount_text(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "غير معروف"

def _payment_match_reason_text(reason: str, event: dict, verification: Optional[dict], bank: Optional[dict]) -> str:
    expected_amount = _payment_amount_text((verification or {}).get("amount"))
    received_amount = _payment_amount_text(event.get("amount"))
    account = str((bank or {}).get("account_number") or "الحساب المحدد").strip()
    messages = {
        "missing_transaction_id": "لم يتم العثور على رقم العملية أو المرجع داخل رسالة التحويل. انسخ نص الرسالة كاملاً كما وصل من البنك أو المحفظة ثم أعد المحاولة.",
        "ambiguous_transaction_id": "تعذر تحديد رقم المرجع تلقائياً لأن الرسالة تحتوي على أكثر من رقم محتمل، مثل الرصيد أو رقم حساب المودع. ستبقى للمراجعة اليدوية ولن يُنشأ سند تلقائي.",
        "unclaimed_transaction": "رقم العملية الموجود في الرسالة غير موجود في طلب تأكيد دفع مفتوح. تأكد من تفاصيل العملية وأرسل طلباً جديداً.",
        "bank_account_mismatch": "الحساب المستلم في رسالة التحويل لا يطابق حساب السداد الذي اخترته. تأكد من رقم الحساب وأعد المحاولة.",
        "amount_mismatch": f"المبلغ غير مطابق: المبلغ في الطلب {expected_amount} بينما المبلغ في الرسالة {received_amount}. تأكد من تفاصيل العملية وأرسل طلباً جديداً.",
        "recipient_account_mismatch": f"رقم الحساب المستلم في الرسالة لا يطابق الحساب المحدد ({account}). تأكد من تفاصيل العملية وأرسل طلباً جديداً.",
    }
    return messages.get(reason, f"تعذر مطابقة العملية ({reason}). انسخ نص الرسالة كاملاً كما وصل وأعد المحاولة.")

async def _match_gateway_message(event: dict, bank: dict):
    transaction_id = event.get("transaction_id")
    if not transaction_id:
        if len(event.get("transaction_candidates") or []) > 1:
            return None, "ambiguous_transaction_id"
        return None, "missing_transaction_id"
    pending = await db.payment_verifications.find_one({
        "$or": [{"client_transaction_id": transaction_id}, {"retry_transaction_id": transaction_id}],
        "status": "pending",
    })
    if not pending:
        return None, "unclaimed_transaction"
    if pending.get("bank_account_id") != bank.get("id"):
        return pending, "bank_account_mismatch"
    gateway_amount = event.get("amount")
    if gateway_amount is None or abs(float(gateway_amount) - float(pending.get("amount") or 0)) > 0.009:
        return pending, "amount_mismatch"
    account_digits = _gateway_digits(bank.get("account_number"))
    message_digits = _gateway_digits(event.get("sms_text"))
    account_in_message = bool(account_digits and len(account_digits) >= 4 and account_digits in message_digits)
    # Some banks intentionally omit the receiving account from their SMS and
    # send only the amount and transaction reference. In that format the
    # signed Gateway sender is the account selector: the inbound route has
    # already required that this Sender ID maps to exactly one active bank.
    # When the configured account number is present, record that stronger
    # evidence; otherwise record the unique Sender ID evidence.
    result = await db.payment_verifications.update_one(
        {"id": pending["id"], "status": "pending"},
        {"$set": {
            "status": "matched",
            "matched_message_id": event["id"],
            "matched_at": now_iso(),
            "match_reason": "exact_reference_amount_account" if account_in_message else "exact_reference_amount_sender",
            "recipient_account_verification": "matched" if account_in_message else "sender_id_unique_account",
        }},
    )
    if result.modified_count:
        return await db.payment_verifications.find_one({"id": pending["id"]}), "matched"
    return await db.payment_verifications.find_one({"id": pending["id"]}), "already_processed"

async def _match_prior_gateway_message(verification: dict, bank: dict):
    """Link one previously authenticated Gateway message to a new customer request.

    Messages are stored only after the inbound endpoint has verified the device,
    HMAC, nonce, Sender ID and parser result. This helper never trusts the
    customer-pasted SMS; it searches the immutable Gateway history by the exact
    reference, bank account and amount, and fails closed when more than one
    unused message is possible.
    """
    transaction_id = str(verification.get("client_transaction_id") or verification.get("retry_transaction_id") or "").strip()
    if not transaction_id:
        return None, "missing_transaction_id"
    try:
        expected_amount = float(verification.get("amount") or 0)
    except (TypeError, ValueError):
        return None, "amount_mismatch"
    if expected_amount <= 0:
        return None, "amount_mismatch"

    history = await _gateway_history_for_bank(transaction_id, bank)
    if not history:
        return None, "not_found"
    amount_matches = [
        event for event in history
        if event.get("amount") is not None
        and abs(float(event.get("amount")) - expected_amount) <= 0.009
    ]
    if not amount_matches:
        return history[0], "amount_mismatch"

    message_ids = [event.get("id") for event in amount_matches if event.get("id")]
    linked = await db.payment_verifications.find({
        "$or": [
            {"matched_message_id": {"$in": message_ids}},
            {"review_message_id": {"$in": message_ids}},
        ]
    }).to_list(5000) if message_ids else []
    used_message_ids = {
        message_id
        for item in linked
        for message_id in (item.get("matched_message_id"), item.get("review_message_id"))
        if message_id and str(item.get("status") or "").lower() != "rejected"
    }
    available = [event for event in amount_matches if event.get("id") not in used_message_ids]
    if len(available) > 1:
        return None, "ambiguous_prior_gateway_message"
    if not available:
        return None, "already_processed"

    event = available[0]
    account_digits = _gateway_digits(bank.get("account_number"))
    message_digits = _gateway_digits(event.get("sms_text"))
    account_in_message = bool(account_digits and len(account_digits) >= 4 and account_digits in message_digits)
    claimed = await db.payment_verifications.update_one(
        {
            "id": verification.get("id"),
            "status": "pending",
            "matched_message_id": {"$exists": False},
        },
        {"$set": {
            "status": "matched",
            "matched_message_id": event["id"],
            "matched_at": now_iso(),
            "matched_from_gateway_history": True,
            "match_reason": "prior_exact_reference_amount_account" if account_in_message else "prior_exact_reference_amount_sender",
            "recipient_account_verification": "matched" if account_in_message else "sender_id_unique_account",
        }},
    )
    if claimed.modified_count:
        return await db.payment_verifications.find_one({"id": verification.get("id")}), "matched"
    return await db.payment_verifications.find_one({"id": verification.get("id")}), "already_processed"

@api.get("/payment-gateway/config")
async def payment_gateway_config(user=Depends(require_perm("settings"))):
    return {"hmac_configured": bool(PAYMENT_GATEWAY_HMAC_SECRET), "device_configured": bool(PAYMENT_GATEWAY_DEVICE_ID), "sender_source": "bank_accounts.gateway_sender_ids"}

@api.put("/payment-gateway/config")
async def update_payment_gateway_config(data: PaymentGatewayConfigIn, user=Depends(require_perm("settings"))):
    return {"ok": True, "sender_source": "bank_accounts.gateway_sender_ids", "hmac_configured": bool(PAYMENT_GATEWAY_HMAC_SECRET), "device_configured": bool(PAYMENT_GATEWAY_DEVICE_ID)}

@api.get("/payment-gateway/devices")
async def list_payment_gateway_devices(user=Depends(require_perm("settings"))):
    settings = await db.settings.find_one({"key": "payment_gateway"}) or {}
    active_id = str(settings.get("active_device_id") or PAYMENT_GATEWAY_DEVICE_ID or "")
    items = await db.payment_gateway_devices.find({}).sort("created_at", -1).to_list(200)
    rows = [clean_doc({**item, "is_active": str(item.get("device_id") or "") == active_id}) for item in items]
    if PAYMENT_GATEWAY_DEVICE_ID and not any(str(x.get("device_id")) == PAYMENT_GATEWAY_DEVICE_ID for x in rows):
        rows.insert(0, {"id": "env-device", "device_id": PAYMENT_GATEWAY_DEVICE_ID, "label": "الجهاز المعتمد في الخادم", "note": "معرّف من متغيرات الخادم ولا يُحذف من الواجهة", "active": True, "is_active": active_id == PAYMENT_GATEWAY_DEVICE_ID, "source": "environment"})
    return {"items": rows, "active_device_id": active_id, "environment_device_configured": bool(PAYMENT_GATEWAY_DEVICE_ID)}

@api.post("/payment-gateway/devices")
async def create_payment_gateway_device(data: PaymentGatewayDeviceIn, user=Depends(require_perm("settings"))):
    device_id = data.device_id.strip()
    existing = await db.payment_gateway_devices.find_one({"device_id": device_id})
    if existing:
        raise HTTPException(status_code=409, detail="معرف الجهاز موجود مسبقاً")
    doc = {"id": str(uuid.uuid4()), "device_id": device_id, "label": data.label.strip(), "note": (data.note or "").strip(), "active": bool(data.active), "created_at": now_iso(), "created_by": user.get("id")}
    await db.payment_gateway_devices.insert_one(doc)
    if data.active:
        await db.settings.update_one({"key": "payment_gateway"}, {"$set": {"active_device_id": device_id, "updated_at": now_iso(), "updated_by": user.get("id")}}, upsert=True)
    await audit_log(user, "create", "payment_gateway_device", doc["id"], None, {"device_id": device_id, "active": bool(data.active)})
    return clean_doc({**doc, "is_active": bool(data.active)})

@api.post("/payment-gateway/devices/{device_id}/activate")
async def activate_payment_gateway_device(device_id: str, user=Depends(require_perm("settings"))):
    device = await db.payment_gateway_devices.find_one({"device_id": device_id})
    if not device:
        if device_id != PAYMENT_GATEWAY_DEVICE_ID:
            raise HTTPException(status_code=404, detail="الجهاز غير موجود")
    elif not device.get("active", True):
        raise HTTPException(status_code=409, detail="الجهاز معطل؛ أضفه أو فعّله أولاً")
    await db.settings.update_one({"key": "payment_gateway"}, {"$set": {"active_device_id": device_id, "updated_at": now_iso(), "updated_by": user.get("id")}}, upsert=True)
    await audit_log(user, "activate", "payment_gateway_device", device_id, None, {"device_id": device_id})
    return {"ok": True, "active_device_id": device_id}

@api.delete("/payment-gateway/devices/{device_id}")
async def delete_payment_gateway_device(device_id: str, user=Depends(require_perm("settings"))):
    if device_id == PAYMENT_GATEWAY_DEVICE_ID:
        raise HTTPException(status_code=409, detail="لا يمكن حذف الجهاز المعرّف في إعدادات الخادم؛ أوقفه أو استبدله من بيئة الخادم أولاً")
    device = await db.payment_gateway_devices.find_one({"device_id": device_id})
    if not device:
        raise HTTPException(status_code=404, detail="الجهاز غير موجود")
    settings = await db.settings.find_one({"key": "payment_gateway"}) or {}
    update = {"updated_at": now_iso(), "updated_by": user.get("id")}
    if settings.get("active_device_id") == device_id:
        update["active_device_id"] = PAYMENT_GATEWAY_DEVICE_ID or ""
    await db.settings.update_one({"key": "payment_gateway"}, {"$set": update}, upsert=True)
    await db.payment_gateway_devices.delete_one({"device_id": device_id})
    await audit_log(user, "delete", "payment_gateway_device", device_id, device, None)
    return {"ok": True, "active_device_id": update.get("active_device_id", settings.get("active_device_id", ""))}

@api.get("/payment-gateway/messages/report")
async def payment_gateway_messages_report(
    start: Optional[str] = None,
    end: Optional[str] = None,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 1000,
    user=Depends(require_perm("settings")),
):
    limit = max(1, min(int(limit or 1000), 5000))
    query: Dict[str, Any] = {}
    date_query: Dict[str, Any] = {}
    if start:
        date_query["$gte"] = f"{start}T00:00:00"
    if end:
        date_query["$lt"] = f"{end}T23:59:59.999999"
    if date_query:
        query["received_at_server"] = date_query
    if q and q.strip():
        safe_q = _re.escape(q.strip())
        query["$or"] = [{"sms_text": {"$regex": safe_q, "$options": "i"}}, {"sender_id": {"$regex": safe_q, "$options": "i"}}, {"transaction_id": {"$regex": safe_q, "$options": "i"}}, {"device_id": {"$regex": safe_q, "$options": "i"}}]
    messages = await db.payment_gateway_messages.find(query).sort("received_at_server", -1).limit(limit).to_list(limit)
    message_ids = [x.get("id") for x in messages if x.get("id")]
    verifications = await db.payment_verifications.find({"$or": [{"matched_message_id": {"$in": message_ids}}, {"review_message_id": {"$in": message_ids}}]}).to_list(5000) if message_ids else []
    direct_purchases = await db.direct_card_purchases.find({"matched_message_id": {"$in": message_ids}}).to_list(5000) if message_ids else []
    direct_sales = await db.sales.find({
        "payment_gateway_message_id": {"$in": message_ids},
        "source": "public_direct_payment",
        "status": {"$ne": "cancelled"},
    }).to_list(5000) if message_ids else []
    by_message = {}
    for verification in verifications:
        for key in (verification.get("matched_message_id"), verification.get("review_message_id")):
            if key:
                by_message[key] = verification
    direct_by_message = {item.get("matched_message_id"): item for item in direct_purchases if item.get("matched_message_id")}
    sale_by_message = {item.get("payment_gateway_message_id"): item for item in direct_sales if item.get("payment_gateway_message_id")}
    rows = []
    for message in messages:
        verification = by_message.get(message.get("id")) or {}
        direct_purchase = direct_by_message.get(message.get("id")) or {}
        direct_sale = sale_by_message.get(message.get("id")) or {}
        if direct_purchase or direct_sale:
            raw_status = str(direct_purchase.get("status") or "unclaimed").lower()
            if direct_sale:
                raw_status = "approved"
            status = "approved" if raw_status == "approved" and (direct_purchase.get("financial_effect") == "posted" or direct_sale) else raw_status
            if raw_status in ("matched", "processing"):
                status = "accepted"
        else:
            raw_status = str(verification.get("status") or "unclaimed").lower()
            status = "approved" if raw_status == "approved" and verification.get("financial_effect") == "posted" else raw_status
            if raw_status in ("matched", "posting"):
                status = "accepted"
            elif not verification:
                status = "unclaimed"
        linked = direct_purchase or direct_sale or verification
        row = clean_doc({
            "message_id": message.get("id"), "received_at": message.get("received_at_server") or message.get("received_at"),
            "sender_id": message.get("sender_id"), "device_id": message.get("device_id"), "bank_account_id": message.get("bank_account_id"),
            "sms_text": message.get("sms_text", ""), "amount": message.get("amount"), "transaction_id": message.get("transaction_id"),
            "status": status, "status_raw": raw_status,
            "operation_type": "direct_card_sale" if direct_purchase or direct_sale else "payment_receipt",
            "financial_effect": linked.get("financial_effect") or ("posted" if direct_sale else "none"),
            "receipt_number": verification.get("receipt_number") or direct_purchase.get("invoice_number") or direct_sale.get("number"),
            "payment_reference": direct_purchase.get("payment_reference") or direct_sale.get("payment_reference") or verification.get("payment_reference") or verification.get("client_transaction_id"),
            "customer_name": verification.get("customer_name", "") or direct_purchase.get("customer_name") or direct_sale.get("customer_name", "مبيعات إلكترونية / نقدية"),
            "customer_id": verification.get("customer_id"),
            "direct_card_purchase_id": direct_purchase.get("id"), "sale_id": direct_purchase.get("sale_id") or direct_sale.get("id"),
            "order_id": direct_purchase.get("order_id"), "invoice_number": direct_purchase.get("invoice_number") or direct_sale.get("number"),
            "failure_reason": direct_purchase.get("failure_reason") or verification.get("review_reason") or verification.get("review_note") or "",
        })
        if status_filter and status != status_filter:
            continue
        rows.append(row)
    counts = {key: sum(1 for row in rows if row.get("status") == key) for key in ("approved", "accepted", "rejected", "manual_review", "unclaimed")}
    return {"items": rows, "counts": counts, "total": len(rows), "filters": {"start": start or "", "end": end or "", "q": q or "", "status": status_filter or ""}}

@api.post("/public/card-order/payment-confirmations")
async def create_public_payment_confirmation(data: PublicPaymentConfirmationIn):
    customer = await _verify_public_customer(data.phone, data.password)
    payment_block = await db.payment_verification_blocks.find_one({"customer_id": customer["id"]})
    failed_attempts = await _count_payment_failures(customer["id"], payment_block)
    if (payment_block and payment_block.get("blocked")) or failed_attempts >= PAYMENT_VERIFICATION_FAILED_LIMIT:
        await db.payment_verification_blocks.update_one(
            {"customer_id": customer["id"]},
            {"$set": {"customer_id": customer["id"], "failed_attempts": failed_attempts, "blocked": True, "updated_at": now_iso()}, "$setOnInsert": {"created_at": now_iso()}},
            upsert=True,
        )
        raise HTTPException(status_code=429, detail=f"تم إيقاف حساب السداد بعد {PAYMENT_VERIFICATION_FAILED_LIMIT} محاولات خاطئة. تواصل مع خدمة العملاء لفك الإيقاف.")
    bank = await db.bank_accounts.find_one({"id": data.bank_account_id, "active": True, "show_in": "portal"})
    if not bank:
        raise HTTPException(status_code=404, detail="حساب السداد غير متاح")
    existing = await db.payment_verifications.find_one({"customer_id": customer["id"], "idempotency_key": data.idempotency_key})
    if existing:
        return clean_doc(existing)
    normalized_input = _normalize_gateway_text(data.sms_text)
    reference_input = _normalize_gateway_text(data.payment_reference or "")
    has_reference = bool(reference_input)
    has_sms_text = len(normalized_input) >= 10
    if has_reference == has_sms_text:
        raise HTTPException(status_code=422, detail="اختر طريقة تحقق واحدة: رقم المرجع أو نص رسالة التحويل")
    selected_method = data.verification_method
    if selected_method not in ("reference", "sms_text"):
        selected_method = "reference" if has_reference else "sms_text"
    if selected_method == "reference" and not has_reference:
        raise HTTPException(status_code=422, detail="أدخل رقم المرجع المحدد للتحقق")
    if selected_method == "sms_text" and not has_sms_text:
        raise HTTPException(status_code=422, detail="الصق نص رسالة التحويل كاملة للتحقق")
    normalized = normalized_input if selected_method == "sms_text" else ""
    provided_reference = reference_input if selected_method == "reference" else ""
    provided_reference = provided_reference.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if provided_reference:
        if not _re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{5,31}", provided_reference):
            raise HTTPException(status_code=422, detail="رقم المرجع غير صالح")
        provided_reference = provided_reference.upper()
    if selected_method == "reference" and provided_reference:
        direct_reference_use = await db.direct_card_purchases.find_one({"payment_reference_normalized": provided_reference})
        if direct_reference_use:
            raise HTTPException(status_code=409, detail="رقم العملية مستخدم من قبل")
    fingerprint_source = normalized.casefold() if normalized else f"reference:{provided_reference.casefold()}"
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    transaction_candidates = _extract_gateway_transaction_candidates(
        normalized,
        [str(data.amount), bank.get("account_number"), provided_reference],
    )
    transaction_id = provided_reference or _extract_gateway_transaction_id(
        normalized,
        [str(data.amount), bank.get("account_number")],
    )
    retry_of = None
    retry_transaction_id = None
    if transaction_id:
        replay = await db.payment_verifications.find_one({"client_transaction_id": transaction_id})
        if replay:
            replay_status = str(replay.get("status") or "").lower()
            if replay_status != "rejected" or replay.get("customer_id") != customer["id"]:
                raise HTTPException(status_code=409, detail="رقم العملية مستخدم من قبل أو ما زال قيد المعالجة")
            # Keep the unique original reference intact, but let the new request
            # match the same signed Gateway reference through a separate field.
            retry_of = replay.get("id")
            retry_transaction_id = transaction_id
            transaction_id = None
    doc = {
        "id": str(uuid.uuid4()), "customer_id": customer["id"], "customer_phone": customer.get("phone"),
        "customer_name": customer.get("name", ""), "bank_account_id": bank["id"], "bank_name": bank.get("bank_name", ""),
        "amount": float(data.amount), "verification_method": selected_method,
        "client_sms_text": data.sms_text.strip() if selected_method == "sms_text" else "",
        "client_payment_reference": provided_reference or None,
        "normalized_message_fingerprint": fingerprint, "client_transaction_id": transaction_id,
        "retry_of": retry_of, "retry_transaction_id": retry_transaction_id,
        "client_transaction_candidates": transaction_candidates,
        "status": "pending", "idempotency_key": data.idempotency_key, "created_at": now_iso(),
        "financial_effect": "none",
    }
    try:
        await db.payment_verifications.insert_one(doc)
    except DuplicateKeyError:
        existing = await db.payment_verifications.find_one({"idempotency_key": data.idempotency_key})
        if existing:
            return clean_doc(existing)
        raise HTTPException(status_code=409, detail="تم تسجيل طلب التأكيد مسبقاً")

    verification = await db.payment_verifications.find_one({"id": doc["id"]})
    prior_event, prior_reason = await _match_prior_gateway_message(verification, bank)
    if prior_event and prior_reason == "matched":
        event = await db.payment_gateway_messages.find_one({"id": prior_event.get("matched_message_id")})
        try:
            verification = await _auto_post_verified_payment(prior_event, event, bank)
        except Exception as exc:
            logger.exception("automatic prior Gateway payment posting failed: %s", exc)
            await db.payment_verifications.update_one(
                {"id": doc["id"], "status": {"$in": ["posting", "matched"]}},
                {"$set": {
                    "status": "manual_review",
                    "review_reason": "تعذر إنشاء سند القبض تلقائياً بعد مطابقة رسالة Gateway السابقة: " + str(exc)[:240],
                    "updated_at": now_iso(),
                    "financial_effect": "none",
                }},
            )
            verification = await db.payment_verifications.find_one({"id": doc["id"]})
    elif prior_reason == "amount_mismatch":
        reason = _payment_match_reason_text(
            "amount_mismatch",
            {"amount": prior_event.get("amount") if prior_event else None},
            verification,
            bank,
        )
        await db.payment_verifications.update_one(
            {"id": doc["id"], "status": "pending"},
            {"$set": {"status": "rejected", "review_reason": reason, "failure_code": "amount_mismatch", "updated_at": now_iso(), "financial_effect": "none"}},
        )
        verification = await db.payment_verifications.find_one({"id": doc["id"]})
        await _notify_payment_confirmation_failure(verification, reason, prior_event)
    elif prior_reason == "ambiguous_prior_gateway_message":
        await db.payment_verifications.update_one(
            {"id": doc["id"], "status": "pending"},
            {"$set": {"status": "manual_review", "review_reason": "وجد النظام أكثر من رسالة Gateway محفوظة بنفس المرجع والمبلغ. لا يمكن اعتماد أي رسالة تلقائياً قبل المراجعة اليدوية.", "failure_code": "ambiguous_prior_gateway_message", "updated_at": now_iso(), "financial_effect": "none"}},
        )
        verification = await db.payment_verifications.find_one({"id": doc["id"]})
    return clean_doc(verification or doc)

@api.post("/public/card-order/payment-confirmations/{verification_id}/status")
async def get_public_payment_confirmation_status(verification_id: str, data: PublicAuth):
    """Return only the authenticated customer's current verification status.

    This is read-only: it never approves a request, creates a receipt, or
    changes a balance. The client may poll it while the signed gateway flow
    or an authorized reviewer advances the state.
    """
    customer = await _verify_public_customer(data.phone, data.password)
    await _expire_unresolved_payment_confirmations(customer_id=customer["id"], verification_id=verification_id)
    verification = await db.payment_verifications.find_one({
        "id": verification_id,
        "customer_id": customer["id"],
    })
    if not verification:
        raise HTTPException(status_code=404, detail="طلب تأكيد الدفع غير موجود")
    stored_status = str(verification.get("status", "pending")).lower()
    payment_block = await db.payment_verification_blocks.find_one({"customer_id": customer["id"]}) or {}
    gateway_message = None
    review_message_id = verification.get("review_message_id")
    if review_message_id:
        gateway_message = await db.payment_gateway_messages.find_one({"id": review_message_id}, {"sms_text": 1, "received_at": 1, "sender_id": 1})
    return clean_doc({
        "id": verification.get("id"),
        "status": stored_status,
        "amount": verification.get("amount", 0),
        "bank_account_id": verification.get("bank_account_id"),
        "created_at": verification.get("created_at"),
        "updated_at": verification.get("updated_at"),
        "matched_at": verification.get("matched_at"),
        "reviewed_at": verification.get("reviewed_at"),
        "review_note": verification.get("review_note", ""),
        "review_reason": verification.get("review_reason", ""),
        "failure_code": verification.get("failure_code", ""),
        "failure_message": (gateway_message or {}).get("sms_text", "") if gateway_message else "",
        "match_reason": verification.get("match_reason", ""),
        "financial_effect": verification.get("financial_effect", "none"),
        "financial_effect_amount": verification.get("financial_effect_amount"),
        "balance_after": verification.get("balance_after"),
        "receipt_number": verification.get("receipt_number"),
        "payment_type": verification.get("payment_type"),
        "payment_reference": verification.get("payment_reference") or verification.get("client_transaction_id") or verification.get("retry_transaction_id"),
        "payment_blocked": bool(payment_block.get("blocked")),
        "failed_attempts": int(payment_block.get("failed_attempts") or 0),
        "failure_limit": PAYMENT_VERIFICATION_FAILED_LIMIT,
    })

async def _auto_post_verified_payment(verification: dict, event: dict, bank: dict) -> dict:
    """Post one exactly matched gateway payment as a customer receipt.

    The unique payment_verification_id on receipts and the process lock make
    this operation at-most-once on the supported standalone Mongo deployment.
    No client-pasted SMS can call this helper; inbound gateway verification is
    the only caller in the automatic path.
    """
    async with financial_mutation_lock:
        verification_id = verification.get("id")
        current = await db.payment_verifications.find_one({"id": verification_id})
        if not current:
            raise HTTPException(status_code=404, detail="طلب التحقق غير موجود")

        existing_receipt = await db.receipts.find_one({"payment_verification_id": verification_id})
        if existing_receipt:
            await db.payment_verifications.update_one(
                {"id": verification_id, "status": {"$in": ["matched", "posting", "manual_review"]}},
                {"$set": {
                    "status": "approved", "receipt_id": existing_receipt.get("id"),
                    "receipt_number": existing_receipt.get("number"),
                    "financial_effect": "posted",
                    "financial_effect_amount": existing_receipt.get("amount"),
                    "balance_after": existing_receipt.get("balance_after"),
                    "payment_type": existing_receipt.get("payment_type"),
                    "payment_reference": existing_receipt.get("payment_reference"),
                    "approved_at": now_iso(), "updated_at": now_iso(),
                }},
            )
            return await db.payment_verifications.find_one({"id": verification_id})

        if current.get("status") not in ("matched", "manual_review", "posting"):
            return current

        await db.payment_verifications.update_one(
            {"id": verification_id, "status": {"$in": ["matched", "manual_review", "posting"]}},
            {"$set": {"status": "posting", "posting_started_at": now_iso(), "updated_at": now_iso()}},
        )
        customer = await db.customers.find_one({"id": current.get("customer_id")})
        if not customer:
            raise HTTPException(status_code=404, detail="حساب العميل غير موجود")
        amount = float(current.get("amount") or 0)
        if amount <= 0:
            raise HTTPException(status_code=422, detail="مبلغ السداد غير صالح")

        provider_type = "wallet" if bank.get("provider_type") == "wallet" else "bank"
        payment_type_label = "محفظة إلكترونية" if provider_type == "wallet" else "حساب بنكي"
        cashbox = await _ensure_bank_cashbox(bank)
        bank_name = str(bank.get("bank_name") or "حساب السداد").strip()
        transaction_id = str(event.get("transaction_id") or current.get("client_transaction_id") or "غير متوفر").strip()
        sender_id = str(event.get("sender_id") or "").strip()
        gateway_text = _normalize_gateway_text(event.get("sms_text"))
        description = (
            f"تسديد تلقائي موثق عبر {payment_type_label}: {bank_name}\n"
            f"مرجع العملية: {transaction_id}\n"
            f"النص المرجعي: {gateway_text}\n"
            f"مصدر الرسالة: {sender_id}"
        )
        number = await next_gwd_number()
        balance_after = await _adjust_party_balance(
            "customer", customer["id"], -amount, number,
            f"سند قبض سداد آلي — {transaction_id}",
        )
        receipt = {
            "id": str(uuid.uuid4()), "number": number,
            "type": "receipt_voucher", "kind": "receipt",
            "receipt_kind": "automatic_payment",
            "party_type": "customer", "party_id": customer["id"],
            "party_name": customer.get("name") or "",
            "amount": amount, "description": description,
            "user_id": PAYMENT_GATEWAY_DEVICE_ID or "payment-gateway",
            "username": "SMS Gateway (تلقائي)", "status": "active",
            "idempotency_key": f"payment-verification:{verification_id}",
            "balance_after": balance_after, "created_at": now_iso(),
            "operation_at": now_iso(), "auto_posted": True,
            "payment_verification_id": verification_id,
            "payment_type": provider_type, "payment_type_label": payment_type_label,
            "bank_account_id": bank.get("id"),
            "cashbox_id": cashbox.get("id"), "cashbox_name": cashbox.get("name"),
            "payment_reference": transaction_id,
            "payment_reference_text": gateway_text,
            "payment_gateway_message_id": event.get("id"),
            "gateway_sender_id": sender_id,
            "gateway_message_received_at": event.get("received_at"),
        }
        try:
            await db.receipts.insert_one(receipt)
        except DuplicateKeyError:
            existing_receipt = await db.receipts.find_one({"payment_verification_id": verification_id})
            if existing_receipt:
                await db.payment_verifications.update_one(
                    {"id": verification_id},
                    {"$set": {
                        "status": "approved", "receipt_id": existing_receipt.get("id"),
                        "receipt_number": existing_receipt.get("number"),
                        "financial_effect": "posted",
                        "financial_effect_amount": existing_receipt.get("amount"),
                        "balance_after": existing_receipt.get("balance_after"),
                        "payment_type": existing_receipt.get("payment_type"),
                        "payment_reference": existing_receipt.get("payment_reference"),
                        "approved_at": now_iso(), "updated_at": now_iso(),
                    }},
                )
                return await db.payment_verifications.find_one({"id": verification_id})
            await _remove_ledger_by_op("customer", customer["id"], number)
            raise
        except Exception:
            await _remove_ledger_by_op("customer", customer["id"], number)
            raise

        await db.payment_verifications.update_one(
            {"id": verification_id, "status": "posting"},
            {"$set": {
                "status": "approved", "receipt_id": receipt["id"],
                "receipt_number": receipt["number"],
                "financial_effect": "posted", "financial_effect_amount": amount,
                "balance_after": balance_after, "approved_at": now_iso(), "updated_at": now_iso(),
                "payment_type": provider_type, "payment_reference": transaction_id,
            }},
        )
        system_user = {"id": PAYMENT_GATEWAY_DEVICE_ID or "payment-gateway", "username": "SMS Gateway (تلقائي)"}
        try:
            notification_message = await _render_message_template("voucher_notification", {
                "number": number, "amount": amount,
                "account_name": customer.get("name") or "",
                "voucher_type": "سند قبض", "description": description,
                "balance_after": balance_after,
            })
            notification_details = {
                "operation": "receipt", "operation_id": receipt["id"], "customer_id": customer["id"],
                "voucher_type": "سند قبض", "number": number, "amount": amount,
                "account_name": customer.get("name") or "", "description": description,
                "balance_after": balance_after, "created_at": receipt.get("created_at"),
                "payment_type": provider_type, "payment_reference": transaction_id,
                "payment_gateway_message_id": event.get("id"),
                "document": {
                    "type": "receipt", "receipt": clean_doc(receipt),
                    "party": {
                        "id": customer.get("id"), "name": customer.get("name") or "",
                        "phone": customer.get("phone") or "",
                        "customer_type": customer.get("customer_type") or "customer",
                        "balance": balance_after,
                    },
                },
            }
            await notify("سند قبض", notification_message, "info", details=notification_details)
            await notify_customer_account(customer["id"], "سند قبض", notification_message, "info", notification_details)
            payment_success_message = (
                f"تم تأكيد عملية الدفع بنجاح وإضافة مبلغ {amount:g} إلى حسابك. "
                f"رقم سند القبض: {number}. المرجع: {transaction_id}."
            )
            payment_success_details = {
                **notification_details,
                "operation": "payment_verification",
                "payment_verification_id": verification_id,
                "status": "approved",
                "financial_effect": "posted",
                "payment_reference": transaction_id,
                "gateway_message_text": gateway_text,
            }
            await notify_customer_account(
                customer["id"], "نجاح تأكيد الدفع", payment_success_message, "success", payment_success_details
            )
            await audit_log(system_user, "create", "receipt", receipt["id"], None, {
                "automatic": True, "payment_verification_id": verification_id,
                "payment_reference": transaction_id, "payment_type": provider_type,
            })
        except Exception as exc:
            logger.warning("automatic payment receipt notification/audit failed: %s", exc)
        return await db.payment_verifications.find_one({"id": verification_id})

@api.post("/payment-gateway/inbound-sms")
async def inbound_payment_gateway_sms(
    request: Request,
    x_gateway_timestamp: Optional[str] = Header(default=None),
    x_gateway_nonce: Optional[str] = Header(default=None),
    x_gateway_device: Optional[str] = Header(default=None),
    x_gateway_signature: Optional[str] = Header(default=None),
):
    if not PAYMENT_GATEWAY_HMAC_SECRET or not PAYMENT_GATEWAY_DEVICE_ID:
        raise HTTPException(status_code=503, detail="بوابة الرسائل غير مهيأة على الخادم")
    if not x_gateway_timestamp or not x_gateway_nonce or not x_gateway_device or not x_gateway_signature:
        raise HTTPException(status_code=401, detail="توقيع بوابة الرسائل مطلوب")
    gateway_settings = await db.settings.find_one({"key": "payment_gateway"}) or {}
    active_gateway_device = str(gateway_settings.get("active_device_id") or PAYMENT_GATEWAY_DEVICE_ID).strip()
    if x_gateway_device != active_gateway_device:
        raise HTTPException(status_code=403, detail="جهاز بوابة غير معتمد")
    try:
        ts = float(x_gateway_timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="وقت توقيع غير صالح")
    if abs(datetime.now(timezone.utc).timestamp() - ts) > 300:
        raise HTTPException(status_code=401, detail="انتهت صلاحية توقيع بوابة الرسائل")
    raw = await request.body()
    signed = f"{x_gateway_timestamp}.{x_gateway_nonce}.".encode() + raw
    expected = hmac.new(PAYMENT_GATEWAY_HMAC_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_gateway_signature.strip().lower()):
        raise HTTPException(status_code=401, detail="توقيع بوابة الرسائل غير صحيح")
    nonce_doc = {"nonce": x_gateway_nonce, "device_id": x_gateway_device, "created_at": now_iso(), "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)}
    try:
        await db.payment_gateway_nonces.insert_one(nonce_doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="تم رفض إعادة إرسال الرسالة نفسها")
    try:
        payload = GatewayInboundSmsIn.model_validate(json.loads(raw.decode("utf-8")))
    except Exception:
        raise HTTPException(status_code=400, detail="بيانات SMS غير صالحة")
    sender_key = _gateway_sender_key(payload.sender_id)
    configured_banks = await db.bank_accounts.find({"active": True}).to_list(500)
    candidates = []
    for candidate in configured_banks:
        if sender_key in await _gateway_sender_allowlist(candidate):
            candidates.append(candidate)
    requested_account = str(payload.bank_account_id or "").strip()
    routing_fallback = ""
    if payload.bank_account_id:
        requested_digits = _gateway_digits(requested_account)
        bank = next((candidate for candidate in candidates if (
            str(candidate.get("id") or "").strip() == requested_account
            or str(candidate.get("account_number") or "").strip() == requested_account
            or (requested_digits and requested_digits == _gateway_digits(candidate.get("account_number")))
        )), None)
        # Older Android builds stored one account id globally. If that stale
        # value remains while the signed Sender ID maps to exactly one account,
        # trust the unique allowlist match instead of losing the SMS. Never do
        # this when the sender maps to multiple accounts.
        if not bank and len(candidates) == 1:
            bank = candidates[0]
            routing_fallback = "unique_sender_overrode_stale_account_id"
        if not bank:
            logger.warning(
                "payment gateway routing rejected: sender=%r requested_account=%r candidates=%s",
                payload.sender_id,
                requested_account,
                [str(item.get("id") or "") for item in candidates],
            )
            raise HTTPException(status_code=403, detail="معرف المحفظة أو مرسل SMS لا يطابق الحساب المحدد")
    elif len(candidates) == 1:
        bank = candidates[0]
    elif not candidates:
        logger.warning("payment gateway routing rejected: sender=%r requested_account=%r candidates=[]", payload.sender_id, requested_account)
        raise HTTPException(status_code=403, detail="مرسل SMS غير موجود في القائمة البيضاء")
    else:
        logger.warning(
            "payment gateway routing rejected: sender=%r requested_account=%r ambiguous_candidates=%s",
            payload.sender_id,
            requested_account,
            [str(item.get("id") or "") for item in candidates],
        )
        raise HTTPException(status_code=409, detail="مصدر SMS مرتبط بأكثر من حساب؛ راجع إعدادات الحسابات البنكية")
    received_at = _gateway_received_at(payload.received_at)
    normalized = _normalize_gateway_text(payload.sms_text)
    jaib_fields = _extract_jaib_gateway_fields(normalized)
    gateway_amount = _extract_gateway_amount(normalized)
    transaction_candidates = _extract_gateway_transaction_candidates(
        normalized,
        [
            gateway_amount,
            bank.get("account_number"),
            jaib_fields.get("balance_after"),
            jaib_fields.get("sender_reference"),
            jaib_fields.get("transaction_id"),
        ],
    )
    gateway_transaction_id = _extract_gateway_transaction_id(
        normalized,
        [gateway_amount, bank.get("account_number")],
    )
    event = {
        "id": str(uuid.uuid4()), "device_id": x_gateway_device, "bank_account_id": bank["id"],
        "sender_id": payload.sender_id.strip(), "sms_text": payload.sms_text,
        "subscription_id": payload.subscription_id,
        "normalized_message_fingerprint": hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest(),
        "transaction_id": gateway_transaction_id, "transaction_candidates": transaction_candidates, "amount": gateway_amount,
        "provider_format": "jaib_compact" if jaib_fields.get("is_jaib_compact") else "generic",
        "provider_balance_after": jaib_fields.get("balance_after"),
        "provider_sender_reference": jaib_fields.get("sender_reference"),
        "provider_operation_type": jaib_fields.get("operation_type"),
        "received_at": received_at.isoformat(), "received_at_server": now_iso(), "immutable": True,
    }
    if routing_fallback:
        event["routing_fallback"] = routing_fallback
        event["requested_bank_account_id"] = requested_account
    try:
        await db.payment_gateway_messages.insert_one(event)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="رسالة SMS مسجلة مسبقاً")
    await _expire_unresolved_direct_card_purchases()
    direct_purchase = await _match_direct_card_purchase(event, bank)
    if direct_purchase:
        try:
            direct_purchase = await _complete_direct_card_purchase(direct_purchase, event, bank)
        except Exception as exc:
            logger.exception("direct /net card purchase completion failed: %s", exc)
            await db.direct_card_purchases.update_one(
                {"id": direct_purchase.get("id"), "status": {"$in": ["pending", "processing"]}},
                {"$set": {"status": "manual_review", "failure_code": "posting_error", "failure_reason": "تعذر تسجيل المبيعات، تحتاج العملية إلى مراجعة الإدارة", "updated_at": now_iso()}},
            )
            direct_purchase = await db.direct_card_purchases.find_one({"id": direct_purchase.get("id")})
            await _notify_admin_payment_failure(
                direct_purchase.get("id"), "direct_card_purchase", float(direct_purchase.get("amount") or 0),
                category_name=direct_purchase.get("category_name") or "", bank_name=bank.get("bank_name") or "",
                failure_code="posting_error", reason="تمت مطابقة الدفع لكن تعذر تسجيل المبيعات وتسليم الكرت",
                payment_reference=direct_purchase.get("payment_reference") or "", status="posted_without_delivery",
            )
        return {"ok": True, "message_id": event["id"], "transaction_id": event.get("transaction_id"), "status": direct_purchase.get("status"), "financial_effect": direct_purchase.get("financial_effect", "none"), "direct_purchase_id": direct_purchase.get("id")}
    # Close unanswered customer requests before attempting a live match. A
    # message received before a request is still handled by the deferred
    # history matcher when the request is created.
    await _expire_unresolved_payment_confirmations()
    verification, reason = await _match_gateway_message(event, bank)
    if verification and reason == "matched":
        try:
            verification = await _auto_post_verified_payment(verification, event, bank)
        except Exception as exc:
            logger.exception("automatic verified payment posting failed: %s", exc)
            await db.payment_verifications.update_one(
                {"id": verification["id"], "status": {"$in": ["posting", "matched"]}},
                {"$set": {
                    "status": "manual_review",
                    "review_reason": "تعذر إنشاء سند القبض تلقائياً: " + str(exc)[:240],
                    "updated_at": now_iso(), "financial_effect": "none",
                }},
            )
            verification = await db.payment_verifications.find_one({"id": verification["id"]})
            await _notify_admin_payment_failure(
                verification.get("id"), "payment_verification", float(verification.get("amount") or 0),
                bank_name=bank.get("bank_name") or "",
                customer={"id": verification.get("customer_id"), "name": verification.get("customer_name", ""), "phone": verification.get("customer_phone", "")},
                failure_code="posting_error", reason="تمت مطابقة الدفع لكن تعذر إنشاء سند القبض تلقائياً",
                payment_reference=verification.get("client_transaction_id") or verification.get("retry_transaction_id") or "",
                status="posted_without_delivery",
            )
    elif verification and reason != "matched" and verification.get("status") == "pending":
        failure_reason = _payment_match_reason_text(reason, event, verification, bank)
        next_status = "rejected" if reason in PAYMENT_DETERMINISTIC_FAILURES else "manual_review"
        await db.payment_verifications.update_one(
            {"id": verification["id"], "status": "pending"},
            {"$set": {
                "status": next_status,
                "review_reason": failure_reason,
                "failure_code": reason,
                "review_message_id": event["id"],
                "updated_at": now_iso(),
            }},
        )
        verification = await db.payment_verifications.find_one({"id": verification["id"]})
        await _notify_admin_payment_failure(
            verification.get("id"), "payment_verification", float(verification.get("amount") or 0),
            bank_name=bank.get("bank_name") or "",
            customer={"id": verification.get("customer_id"), "name": verification.get("customer_name", ""), "phone": verification.get("customer_phone", "")},
            failure_code=reason, reason=failure_reason,
            payment_reference=verification.get("client_transaction_id") or verification.get("retry_transaction_id") or "",
            status=next_status,
        )
        if next_status == "rejected":
            await _notify_payment_confirmation_failure(verification, failure_reason, event)
    return {"ok": True, "message_id": event["id"], "transaction_id": event.get("transaction_id"), "status": verification.get("status") if verification else "unclaimed", "financial_effect": verification.get("financial_effect", "none") if verification else "none"}

@api.get("/payment-verifications")
async def list_payment_verifications(status_filter: Optional[str] = None, user=Depends(require_perm("receipts"))):
    query = {"status": status_filter} if status_filter else {}
    docs = await db.payment_verifications.find(query).sort("created_at", -1).limit(500).to_list(500)
    return [clean_doc(x) for x in docs]

@api.get("/payment-verifications/blocked-customers")
async def list_blocked_payment_customers(user=Depends(require_perm("settings"))):
    blocks = await db.payment_verification_blocks.find({"blocked": True}).sort("updated_at", -1).to_list(500)
    customer_ids = [item.get("customer_id") for item in blocks if item.get("customer_id")]
    customers = await db.customers.find({"id": {"$in": customer_ids}}, {"id": 1, "name": 1, "phone": 1}).to_list(len(customer_ids)) if customer_ids else []
    customer_map = {item.get("id"): item for item in customers}
    return [clean_doc({**item, "customer_name": (customer_map.get(item.get("customer_id")) or {}).get("name", ""), "phone": (customer_map.get(item.get("customer_id")) or {}).get("phone", "")}) for item in blocks]

@api.post("/payment-verifications/blocked-customers/{customer_id}/unlock")
async def unlock_payment_customer(customer_id: str, user=Depends(require_perm("settings"))):
    customer = await db.customers.find_one({"id": customer_id}, {"id": 1, "name": 1, "phone": 1})
    if not customer:
        raise HTTPException(status_code=404, detail="حساب العميل غير موجود")
    reset_at = now_iso()
    result = await db.payment_verification_blocks.update_one(
        {"customer_id": customer_id},
        {"$set": {"blocked": False, "failed_attempts": 0, "failure_reset_at": reset_at, "unlocked_at": reset_at, "unlocked_by": user.get("id"), "updated_at": reset_at}},
        upsert=True,
    )
    await audit_log(user, "unlock", "payment_verification_block", customer_id, None, {"customer_phone": customer.get("phone", "")})
    return {"ok": True, "customer_id": customer_id, "blocked": False, "failed_attempts": 0}

@api.post("/payment-verifications/{verification_id}/review")
async def review_payment_verification(verification_id: str, data: PaymentVerificationReviewIn, user=Depends(require_perm("receipts"))):
    doc = await db.payment_verifications.find_one({"id": verification_id})
    if not doc:
        raise HTTPException(status_code=404, detail="طلب التحقق غير موجود")
    if doc.get("status") in ("approved", "rejected"):
        raise HTTPException(status_code=409, detail="تمت مراجعة الطلب مسبقاً")
    if data.status == "approved":
        message_id = doc.get("matched_message_id") or doc.get("review_message_id")
        event = await db.payment_gateway_messages.find_one({"id": message_id}) if message_id else None
        bank = await db.bank_accounts.find_one({"id": doc.get("bank_account_id"), "active": True})
        if not event or not bank:
            raise HTTPException(status_code=409, detail="لا توجد رسالة Gateway موثقة يمكن اعتمادها")
        await db.payment_verifications.update_one(
            {"id": verification_id, "status": {"$nin": ["approved", "rejected"]}},
            {"$set": {"status": "matched", "review_note": (data.note or "").strip(), "reviewed_by": user.get("id"), "reviewed_at": now_iso(), "updated_at": now_iso()}},
        )
        try:
            result = await _auto_post_verified_payment(doc, event, bank)
        except Exception as exc:
            await db.payment_verifications.update_one(
                {"id": verification_id, "status": {"$in": ["posting", "matched"]}},
                {"$set": {"status": "manual_review", "review_reason": "تعذر إنشاء سند القبض تلقائياً: " + str(exc)[:240], "updated_at": now_iso(), "financial_effect": "none"}},
            )
            result = await db.payment_verifications.find_one({"id": verification_id})
        await audit_log(user, "payment_verification:approved", "payment_verification", verification_id, doc, {"automatic_receipt": True, "note": data.note or ""})
        return clean_doc(result)
    update = {"status": data.status, "review_note": (data.note or "").strip(), "reviewed_by": user.get("id"), "reviewed_at": now_iso(), "updated_at": now_iso(), "financial_effect": "none"}
    await db.payment_verifications.update_one({"id": verification_id, "status": {"$nin": ["approved", "rejected"]}}, {"$set": update})
    if data.status == "rejected":
        review_message = await db.payment_gateway_messages.find_one({"id": doc.get("review_message_id")}) if doc.get("review_message_id") else None
        await _notify_payment_confirmation_failure(
            {**doc, **update},
            update.get("review_note") or "تم رفض عملية تأكيد الدفع بعد المراجعة اليدوية",
            review_message,
        )
    await audit_log(user, f"payment_verification:{data.status}", "payment_verification", verification_id, doc, update)
    return clean_doc(await db.payment_verifications.find_one({"id": verification_id}))

# ================= DIRECT CARD PURCHASE (PUBLIC /net) =================
def _direct_reference(value: Any) -> str:
    return _re.sub(r"\s+", "", str(value or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))).upper()


async def _direct_reference_is_committed(reference: str, exclude_purchase_id: Optional[str] = None) -> bool:
    """Return whether a reference has a committed financial/request claim.

    A failed or timed-out attempt is not a financial use of the reference and
    may be retried.  Once a direct request is matched to a Gateway message,
    has a sale/invoice, or has posted a customer receipt, the reference is
    consumed and must remain protected against duplicate use.
    """
    normalized = _direct_reference(reference)
    if not normalized:
        return False
    sale = await db.sales.find_one({
        "$or": [
            {"payment_reference": normalized},
            {"payment_gateway_reference": normalized},
        ],
        "status": {"$ne": "cancelled"},
    })
    if sale:
        return True
    purchase_query: Dict[str, Any] = {
        "payment_reference_normalized": normalized,
        "$or": [
            {"matched_message_id": {"$exists": True}},
            {"sale_id": {"$exists": True}},
            {"order_id": {"$exists": True}},
            {"invoice_number": {"$exists": True}},
            {"financial_effect": "posted"},
            {"status": "approved"},
        ],
    }
    if exclude_purchase_id:
        purchase_query["id"] = {"$ne": exclude_purchase_id}
    if await db.direct_card_purchases.find_one(purchase_query):
        return True
    verification_reference_query = {
        "$or": [
            {"client_payment_reference": normalized},
            {"client_transaction_id": normalized},
            {"retry_transaction_id": normalized},
            {"payment_reference": normalized},
        ],
    }
    committed_verification_query = {
        "$and": [
            verification_reference_query,
            {"$or": [
                {"financial_effect": "posted"},
                {"receipt_id": {"$exists": True}},
                {"receipt_number": {"$exists": True}},
                {"status": {"$in": ["matched", "posting", "approved"]}},
            ]},
        ],
    }
    return bool(await db.payment_verifications.find_one(committed_verification_query))


async def _complete_direct_card_purchase(purchase: dict, event: dict, bank: dict) -> dict:
    """Complete one unauthenticated /net purchase only after Gateway matching.

    The browser submits only a reference. It never creates a sale or changes a
    balance; this function is called from the signed inbound Gateway path (or
    its deferred matcher) after the exact bank, amount, and reference match.
    """
    current = await db.direct_card_purchases.find_one({"id": purchase.get("id")})
    if not current or current.get("status") == "approved":
        return current or purchase
    if current.get("status") != "pending":
        return current
    amount = _numeric_amount(current.get("amount"), 0)
    event_amount = _numeric_amount(event.get("amount"), 0)
    event_reference = _direct_reference(event.get("transaction_id"))
    requested_reference = _direct_reference(current.get("payment_reference"))
    if await _direct_reference_is_committed(requested_reference, exclude_purchase_id=current.get("id")):
        await db.direct_card_purchases.update_one(
            {"id": current["id"], "status": "pending"},
            {"$set": {"status": "rejected", "failure_code": "reference_already_used", "failure_reason": "رقم العملية مستخدم من قبل", "updated_at": now_iso()}},
        )
        await _notify_admin_payment_failure(current.get("id"), "direct_card_purchase", amount, current.get("category_name") or "", bank_name=bank.get("bank_name") or "", failure_code="reference_already_used", reason="رقم العملية مستخدم من قبل", payment_reference=requested_reference)
        return await db.direct_card_purchases.find_one({"id": current["id"]})
    if not event_reference or event_reference != requested_reference:
        await db.direct_card_purchases.update_one(
            {"id": current["id"], "status": "pending"},
            {"$set": {"status": "rejected", "failure_code": "reference_mismatch", "failure_reason": "رقم مرجع العملية غير مطابق", "updated_at": now_iso()}},
        )
        await _notify_admin_payment_failure(current.get("id"), "direct_card_purchase", amount, current.get("category_name") or "", bank_name=bank.get("bank_name") or "", failure_code="reference_mismatch", reason="رقم مرجع العملية غير مطابق", payment_reference=requested_reference)
        return await db.direct_card_purchases.find_one({"id": current["id"]})
    if abs(event_amount - amount) > 0.0001:
        await db.direct_card_purchases.update_one(
            {"id": current["id"], "status": "pending"},
            {"$set": {"status": "rejected", "failure_code": "amount_mismatch", "failure_reason": "المبلغ المحول لا يساوي مبلغ فئة الكرت", "updated_at": now_iso()}},
        )
        await _notify_admin_payment_failure(current.get("id"), "direct_card_purchase", amount, current.get("category_name") or "", bank_name=bank.get("bank_name") or "", failure_code="amount_mismatch", reason="المبلغ المحول لا يساوي مبلغ فئة الكرت", payment_reference=requested_reference)
        return await db.direct_card_purchases.find_one({"id": current["id"]})
    claim_purchase = await db.direct_card_purchases.update_one(
        {"id": current["id"], "status": "pending"},
        {"$set": {"status": "processing", "updated_at": now_iso()}},
    )
    if claim_purchase.modified_count != 1:
        return await db.direct_card_purchases.find_one({"id": current["id"]})
    category = await db.card_categories.find_one({"id": current.get("category_id"), "status": "active"})
    if not category:
        raise HTTPException(status_code=404, detail="فئة الكرت غير موجودة")
    cards = await db.cards.find({"category_id": category["id"], "status": "available"}).limit(1).to_list(1)
    if not cards:
        await db.direct_card_purchases.update_one(
            {"id": current["id"], "status": "processing"},
            {"$set": {"status": "rejected", "failure_code": "no_stock", "failure_reason": "لا يتوفر كرت من هذه الفئة حالياً. يمكنك إعادة المحاولة لاحقاً بنفس رقم العملية.", "retryable": True, "updated_at": now_iso()}},
        )
        await _notify_admin_payment_failure(current.get("id"), "direct_card_purchase", amount, current.get("category_name") or "", bank_name=bank.get("bank_name") or "", failure_code="no_stock", reason="لا يتوفر كرت من هذه الفئة حالياً", payment_reference=requested_reference)
        return await db.direct_card_purchases.find_one({"id": current["id"]})
    card = cards[0]
    claim = await db.cards.update_one(
        {"id": card["id"], "status": "available"},
        {"$set": {"status": "sold", "sold_at": now_iso(), "sold_to": "public-net", "sold_source": "public_direct_payment"}},
    )
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="تعذر حجز الكرت، أعد المحاولة")
    cashbox = await _ensure_bank_cashbox(bank)
    number = await next_gwd_number()
    payment_name = str(bank.get("bank_name") or "حساب السداد").strip()
    invoice_payment_label = f"مبيعات إلكترونية / {payment_name} / نقدية"
    sale = {
        "id": str(uuid.uuid4()), "number": number, "type": "sale",
        "customer_id": None, "customer_name": "مبيعات إلكترونية / نقدية",
        "sale_type": "cash", "source": "public_direct_payment",
        "items": [{"category_id": category["id"], "category_name": category.get("name"), "quantity": 1, "price": amount, "total": amount, "card_numbers": [card.get("number")], "use_numbered": True}],
        "subtotal": amount, "discount": 0, "total": amount, "paid": amount, "remaining": 0,
        "notes": "مبيعات إلكترونية / نقدية عبر /net — سداد Gateway موثق",
        "status": "active", "created_at": now_iso(), "operation_at": now_iso(),
        "idempotency_key": current.get("idempotency_key"), "success": True,
        "cards": [card.get("number")], "quantity_from_stock": 0,
        "bank_account_id": bank.get("id"), "cashbox_id": cashbox.get("id"), "cashbox_name": cashbox.get("name"),
        "payment_reference": event_reference, "payment_gateway_message_id": event.get("id"),
        "payment_type": "wallet" if bank.get("provider_type") == "wallet" else "bank",
        "payment_type_label": payment_name, "invoice_payment_label": invoice_payment_label,
    }
    order = {
        "id": str(uuid.uuid4()), "number": number, "customer_id": None,
        "customer_name": "مبيعات إلكترونية / نقدية", "phone": "",
        "category_id": category["id"], "category_name": category.get("name"), "quantity": 1,
        "total": amount, "cards": [card.get("number")], "status": "delivered",
        "source": "public_direct_payment", "bank_account_id": bank.get("id"), "cashbox_id": cashbox.get("id"),
        "payment_reference": event_reference, "payment_type_label": payment_name, "invoice_payment_label": invoice_payment_label,
        "created_at": now_iso(), "idempotency_key": current.get("idempotency_key"),
    }
    sale_inserted = False
    try:
        await db.sales.insert_one(sale)
        await log_card_event(card.get("id"), "sold", card.get("number"), None,
                             {"sale_id": sale.get("id"), "sale_number": sale.get("number"),
                              "customer_name": sale.get("customer_name") or "بيع مباشر"},
                             f"بيع مباشر {sale.get('number')}")
        sale_inserted = True
        await db.orders.insert_one(order)
        await db.direct_card_purchases.update_one(
            {"id": current["id"], "status": "processing"},
            {"$set": {"status": "approved", "sale_id": sale["id"], "order_id": order["id"], "invoice_number": number, "card_number": card.get("number"), "matched_message_id": event.get("id"), "financial_effect": "posted", "updated_at": now_iso()}},
        )
    except Exception:
        if sale_inserted:
            await db.sales.delete_one({"id": sale["id"]})
        await db.orders.delete_one({"id": order["id"]})
        await db.cards.update_one({"id": card["id"], "sold_to": "public-net"}, {"$set": {"status": "available"}, "$unset": {"sold_at": "", "sold_to": "", "sold_source": ""}})
        raise
    try:
        # Keep the immutable SMS content untouched while adding an auditable
        # relation to the request, sale and invoice created from it.
        await db.payment_gateway_messages.update_one(
            {"id": event.get("id")},
            {"$set": {
                "direct_card_purchase_id": current["id"],
                "sale_id": sale["id"],
                "order_id": order["id"],
                "invoice_number": number,
                "linked_type": "direct_card_sale",
                "linked_at": now_iso(),
                "financial_effect": "posted",
            }},
        )
    except Exception as exc:
        logger.warning("direct Gateway message link update failed: %s", exc)
    try:
        await notify("مبيعات إلكترونية / نقدية", f"تم بيع كرت {category.get('name','')} عبر {payment_name} بمبلغ {amount:g} — المرجع {event_reference}", "success", details={"operation": "public_direct_card_purchase", "operation_id": sale["id"], "amount": amount, "cashbox_id": cashbox.get("id"), "payment_name": payment_name, "invoice_payment_label": invoice_payment_label})
    except Exception as exc:
        logger.warning("direct public card notification failed: %s", exc)
    return await db.direct_card_purchases.find_one({"id": current["id"]})

async def _match_direct_card_purchase(event: dict, bank: dict) -> Optional[dict]:
    reference = _direct_reference(event.get("transaction_id"))
    if not reference:
        return None
    pending = await db.direct_card_purchases.find({"bank_account_id": bank.get("id"), "status": "pending"}).sort("created_at", 1).to_list(50)
    matches = []
    for item in pending:
        if _direct_reference(item.get("payment_reference")) != reference:
            continue
        if not await _direct_reference_is_committed(reference, exclude_purchase_id=item.get("id")):
            matches.append(item)
    if len(matches) != 1:
        if len(matches) > 1:
            logger.warning("ambiguous /net reference=%s bank=%s", reference, bank.get("id"))
        return None
    return matches[0]

@api.post("/public/net/purchase")
@idempotent_operation("public_net_purchase", "direct_card_purchases")
async def public_direct_card_purchase(data: DirectCardPurchaseIn):
    bank = await db.bank_accounts.find_one({"id": data.bank_account_id, "active": True})
    if not bank or not _bank_visible_in(bank, "portal"):
        raise HTTPException(status_code=404, detail="حساب السداد غير متاح")
    category = await db.card_categories.find_one({"id": data.category_id, "status": "active", "show_in_public": {"$ne": False}, "kind": {"$ne": "balance"}})
    if not category:
        raise HTTPException(status_code=404, detail="فئة الكرت غير موجودة")
    unit_price = category.get("sale_price_customer")
    if unit_price is None:
        unit_price = category.get("sale_price", 0)
    reference = _direct_reference(data.payment_reference)
    if len(reference) < 6:
        raise HTTPException(status_code=400, detail="رقم مرجع العملية غير صالح")
    existing = await db.direct_card_purchases.find_one({"payment_reference_normalized": reference})
    if existing and await _direct_reference_is_committed(reference, exclude_purchase_id=existing.get("id")):
        raise HTTPException(status_code=409, detail="رقم العملية مستخدم من قبل")
    if await _direct_reference_is_committed(reference):
        raise HTTPException(status_code=409, detail="رقم العملية مستخدم من قبل")
    purchase_update = {
        "category_id": category["id"], "category_name": category.get("name"),
        "amount": _numeric_amount(unit_price), "bank_account_id": bank["id"], "bank_name": bank.get("bank_name"),
        "payment_reference": str(data.payment_reference).strip(), "payment_reference_normalized": reference,
        "status": "pending", "financial_effect": "none", "created_at": now_iso(), "updated_at": now_iso(),
        "idempotency_key": data.idempotency_key,
    }
    if existing:
        if existing.get("status") == "processing":
            raise HTTPException(status_code=409, detail="العملية قيد المعالجة، انتظر النتيجة")
        # A rejected/expired attempt did not consume the payment. Reuse its
        # unique reference row and clear only non-financial outcome fields so
        # the same SMS reference can be submitted again safely.
        await db.direct_card_purchases.update_one(
            {"id": existing["id"], "status": {"$ne": "processing"}},
            {"$set": purchase_update, "$unset": {
                "failure_code": "", "failure_reason": "", "matched_message_id": "",
                "sale_id": "", "order_id": "", "invoice_number": "", "card_number": "", "retryable": "",
            }},
        )
        purchase = await db.direct_card_purchases.find_one({"id": existing["id"]})
    else:
        purchase = {"id": str(uuid.uuid4()), **purchase_update}
        await db.direct_card_purchases.insert_one(purchase)
    # Use the same exact-reference historical matcher as balance deposits.
    # A bank account may have been recreated while an immutable Gateway SMS
    # still carries the retired bank UUID; the unique Sender ID fallback is
    # already constrained by _gateway_history_for_bank.
    events = await _gateway_history_for_bank(reference, bank)
    event = next((item for item in events if _direct_reference(item.get("transaction_id")) == reference), None)
    if event:
        purchase = await _complete_direct_card_purchase(purchase, event, bank)
    return clean_doc(purchase)

async def _expire_unresolved_direct_card_purchases(purchase_id: Optional[str] = None):
    """Close unanswered direct-card requests using the same short response window as payment confirmation."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=PAYMENT_VERIFICATION_RESPONSE_WINDOW_SECONDS)).isoformat()
    query: Dict[str, Any] = {"status": "pending", "created_at": {"$lte": cutoff}}
    if purchase_id:
        query["id"] = purchase_id
    pending = await db.direct_card_purchases.find(query).to_list(100)
    result = await db.direct_card_purchases.update_many(
        query,
        {"$set": {
            "status": "rejected",
            "failure_code": "gateway_response_timeout",
            "failure_reason": "انتهت مهلة الاستجابة، أعد المحاولة.",
            "financial_effect": "none",
            "updated_at": now_iso(),
        }},
    )
    for purchase in pending:
        await _notify_admin_payment_failure(
            purchase.get("id"), "direct_card_purchase", float(purchase.get("amount") or 0),
            category_name=purchase.get("category_name") or "", bank_name=purchase.get("bank_name") or "",
            failure_code="gateway_response_timeout", reason="انتهت مهلة الاستجابة، أعد المحاولة.",
            payment_reference=purchase.get("payment_reference") or "", status="rejected",
        )
    return result.modified_count

@api.get("/public/net/purchase/{purchase_id}")
async def public_direct_card_purchase_status(purchase_id: str):
    await _expire_unresolved_direct_card_purchases(purchase_id)
    purchase = await db.direct_card_purchases.find_one({"id": purchase_id})
    if not purchase:
        raise HTTPException(status_code=404, detail="طلب الشراء غير موجود")
    return clean_doc(purchase)

# ================= CARD ORDERS (PUBLIC) =================
@api.post("/public/card-order/login")
async def public_login(data: CardOrderPublicLogin):
    # Rate limit: PORTAL_LOGIN_FAILED_LIMIT failed in 24h => block
    blocks = await db.public_blocks.find_one({"phone": data.phone})
    if blocks and blocks.get("blocked_until") and blocks["blocked_until"] > now_iso():
        raise HTTPException(status_code=429, detail=f"تم حظر الإدخال بسبب تجاوز عدد المحاولات الفاشلة. مدة الحظر: 24 ساعة")
    customer = await db.customers.find_one({"phone": data.phone})
    if not customer:
        await db.card_order_attempts.insert_one({
            "id": str(uuid.uuid4()), "phone": data.phone, "status": "rejected_not_found",
            "reason": "المستخدم غير موجود", "attempt_password": data.password,
            "created_at": now_iso(),
        })
        await _alert_failed_login("portal", data.phone, data.password, "المستخدم غير موجود")
        # Count non-existent-phone attempts toward the same rate limit
        cur = await db.public_blocks.find_one({"phone": data.phone}) or {}
        failed = cur.get("failed", 0) + 1
        update = {"phone": data.phone, "failed": failed, "last_failed_at": now_iso()}
        if failed >= PORTAL_LOGIN_FAILED_LIMIT:
            block_until = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            update["blocked_until"] = block_until
            update["blocked_at"] = now_iso()
            update["failed"] = 0
            _blk1_title = "تم حظر رقم غير مسجل"
            _blk1_msg = f"تم حظر الرقم {data.phone} بسبب تجاوز عدد المحاولات الفاشلة (رقم غير مسجل). مدة الحظر: 24 ساعة."
            _blk1_id = str(uuid.uuid4())
            await db.notifications.insert_one({
                "id": _blk1_id, "title": _blk1_title,
                "message": _blk1_msg,
                "type": "warning", "read": False, "created_at": now_iso(),
            })
            await _notify_push(_blk1_id, _blk1_title, _blk1_msg, "warning", {"category": "portal_block", "phone": data.phone})
        await db.public_blocks.update_one({"phone": data.phone}, {"$set": update}, upsert=True)
        raise HTTPException(status_code=404, detail="لا تمتلك حساباً بهذا الرقم، قم بإنشاء حساب الآن")
    if customer.get("password") != data.password:
        await db.card_order_attempts.insert_one({
            "id": str(uuid.uuid4()), "customer_id": customer.get("id"), "customer_name": customer.get("name"),
            "phone": data.phone, "status": "login_failed",
            "reason": "كلمة المرور خاطئة", "attempt_password": data.password,
            "created_at": now_iso(),
        })
        await _alert_failed_login("portal", data.phone, data.password, "كلمة المرور خاطئة",
                                  {"customer_name": customer.get("name") or ""})
        # increment failed counter
        cur = await db.public_blocks.find_one({"phone": data.phone}) or {}
        failed = cur.get("failed", 0) + 1
        update = {"phone": data.phone, "failed": failed, "last_failed_at": now_iso()}
        if failed >= PORTAL_LOGIN_FAILED_LIMIT:
            block_until = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            update["blocked_until"] = block_until
            update["blocked_at"] = now_iso()
            update["failed"] = 0
            _blk2_title = "تم حظر عميل"
            _blk2_msg = f"تم حظر العميل {customer.get('name','')} ({data.phone}) بسبب تجاوز عدد المحاولات الفاشلة. مدة الحظر: 24 ساعة."
            _blk2_id = str(uuid.uuid4())
            await db.notifications.insert_one({
                "id": _blk2_id, "title": _blk2_title,
                "message": _blk2_msg,
                "type": "warning", "read": False, "created_at": now_iso(),
            })
            await _notify_push(_blk2_id, _blk2_title, _blk2_msg, "warning", {"category": "portal_block", "phone": data.phone, "customer_id": customer.get("id")})
        await db.public_blocks.update_one({"phone": data.phone}, {"$set": update}, upsert=True)
        raise HTTPException(status_code=401, detail="كلمة السر غير صحيحة")
    if customer.get("status") == "disabled":
        await db.card_order_attempts.insert_one({
            "id": str(uuid.uuid4()), "customer_id": customer.get("id"), "customer_name": customer.get("name"),
            "phone": data.phone, "status": "login_disabled",
            "reason": "الحساب معطل", "created_at": now_iso(),
        })
        raise HTTPException(status_code=403, detail="الحساب معطل")
    # Device binding check (single field, no extra query). First-time binds silently.
    # الحسابات قيد التوثيق (المُنشأة تلقائياً من البوابة) لا تُقيَّد بجهاز قبل توثيق الإدارة.
    _unverified = (customer.get("verified") is False)
    bound = customer.get("bound_device")
    incoming = (data.device_id or "").strip()
    if (not _unverified) and bound and incoming and bound != incoming:
        # Do NOT count as a password-failed attempt; the password was correct.
        await db.card_order_attempts.insert_one({
            "id": str(uuid.uuid4()), "customer_id": customer.get("id"), "customer_name": customer.get("name"),
            "phone": data.phone, "status": "login_device",
            "reason": "الهاتف غير مرتبط بالحساب", "attempt_password": "",
            "device_id": incoming[:120], "bound_device": (bound or "")[:120],
            "created_at": now_iso(),
        })
        # إشعار الإدارة: محاولة دخول من هاتف غير مرتبط بالحساب (كلمة المرور صحيحة)
        await _alert_failed_login("portal", data.phone, "صحيحة", "الهاتف غير مرتبط بالحساب",
                                  {"customer_name": customer.get("name") or ""})
        raise HTTPException(
            status_code=403,
            detail="الهاتف غير مرتبط بالحساب. إذا قمت باستبدال هاتفك القديم، يرجى التواصل مع خدمة العملاء لطلب كلمة المرور.",
        )
    if (not _unverified) and not bound and incoming:
        await db.customers.update_one(
            {"id": customer["id"]},
            {"$set": {"bound_device": incoming, "bound_device_at": now_iso()}},
        )
    # reset failed counter on success
    await db.public_blocks.update_one({"phone": data.phone}, {"$set": {"failed": 0}}, upsert=True)
    credit_limit = _customer_credit_limit(customer)
    balance = _numeric_amount(customer.get("balance"), 0.0)
    return {
        "id": customer["id"], "name": customer["name"], "phone": customer["phone"],
        "short_name": _short_customer_name(customer.get("name")),
        "phone_last2": _phone_last_two(customer.get("phone")),
        "alternative_number": customer.get("alternative_number") or await _ensure_customer_alternative_number(customer),
        "credit_limit": credit_limit, "balance": balance,
        "customer_type": customer.get("customer_type", "customer"),
        "available": max(0.0, credit_limit - balance),
        "verified": customer.get("verified") is not False,
    }

class PublicVerificationCodeIn(BaseModel):
    phone: str
    password: str
    code: str

@api.post("/public/card-order/request-verification")
async def public_request_verification(data: Dict[str, Any]):
    """يسجل طلب التوثيق فقط؛ لا يرسل قناة ولا ينشئ رمزاً قبل موافقة الإدارة."""
    phone = str((data or {}).get("phone") or "").strip()
    password = str((data or {}).get("password") or "")
    if not phone or not password:
        raise HTTPException(status_code=400, detail="رقم الهاتف وكلمة المرور مطلوبان")
    customer = await db.customers.find_one({"phone": phone})
    if not customer or customer.get("password") != password:
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة")
    if customer.get("verified") is not False:
        return {"ok": True, "already_verified": True, "status": "verified"}
    current = str(customer.get("verification_status") or "not_requested")
    if current in {"requested", "awaiting_code"}:
        return {"ok": True, "already_verified": False, "status": current, "already_requested": True}
    now = now_iso()
    await db.customers.update_one({"id": customer["id"]}, {"$set": {
        "verification_status": "requested", "verification_requested_at": now,
        "verification_code_hash": None, "verification_code_channel": None,
        "verification_code_attempts": 0, "updated_at": now,
    }})
    msg = (
        f"طلب العميل {customer.get('name') or ''} توثيق حسابه\n"
        f"الهاتف: {phone}\nالعنوان: {customer.get('address') or ''}\n"
        f"تاريخ ووقت الطلب: {now}"
    )
    doc = {
        "id": str(uuid.uuid4()), "title": "طلب توثيق حساب",
        "message": msg, "type": "warning", "category": "verification_request",
        "ref_id": customer["id"], "read": False, "created_at": now,
        "details": {"category": "verification_request", "operation": "verification_request",
                    "customer_id": customer["id"], "phone": phone,
                    "name": customer.get("name") or "", "address": customer.get("address") or "",
                    "requested_at": now},
    }
    await db.notifications.insert_one(doc)
    await _notify_push(doc["id"], doc["title"], msg, "warning",
                       {"category": "verification_request", "customer_id": customer["id"]})
    return {"ok": True, "already_verified": False, "status": "requested", "already_requested": False}

@api.post("/public/card-order/confirm-verification")
async def public_confirm_verification(data: PublicVerificationCodeIn):
    phone = (data.phone or "").strip()
    password = data.password or ""
    code = str(data.code or "").strip()
    if not _re.fullmatch(r"\d{6}", code):
        raise HTTPException(status_code=400, detail="رمز التوثيق يجب أن يكون 6 أرقام")
    customer = await db.customers.find_one({"phone": phone})
    if not customer or customer.get("password") != password:
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة")
    if customer.get("verified") is not False:
        return {"ok": True, "verified": True, "already_verified": True}
    if str(customer.get("verification_status") or "") != "awaiting_code":
        raise HTTPException(status_code=400, detail="لم تتم الموافقة على طلب التوثيق بعد")
    attempts = int(customer.get("verification_code_attempts") or 0)
    if attempts >= 5:
        raise HTTPException(status_code=429, detail="تم تجاوز عدد محاولات إدخال الرمز")
    expected = str(customer.get("verification_code_hash") or "")
    actual = hashlib.sha256(f"{JWT_SECRET}:{customer['id']}:{code}".encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected, actual):
        await db.customers.update_one({"id": customer["id"]}, {"$inc": {"verification_code_attempts": 1}})
        raise HTTPException(status_code=400, detail="رمز التوثيق غير صحيح")
    now = now_iso()
    verification_channel = customer.get("verification_code_channel") or ""
    await db.customers.update_one({"id": customer["id"]}, {"$set": {
        "verified": True, "verification_status": "verified", "verified_at": now,
        "verification_method": "admin_approved_code", "verification_channel": verification_channel,
        "updated_at": now,
    }, "$unset": {"verification_code_hash": "", "verification_code_channel": ""}})
    await db.notifications.update_many({"category": "verification_request", "ref_id": customer["id"]}, {"$set": {"read": True, "read_at": now}})
    await audit_log({"id": customer["id"], "username": customer.get("name") or "customer"},
                    "customer_self_verification", "customer", customer["id"], None,
                    {"channel": verification_channel})
    return {"ok": True, "verified": True, "already_verified": False}

@api.post("/public/card-order/verification-status")
async def public_verification_status(data: PublicAuth):
    """حالة توثيق الحساب للعميل: غير مطلوب / طلب قيد المراجعة / بانتظار الرمز / موثّق."""
    customer = await db.customers.find_one({"phone": data.phone})
    if not customer or customer.get("password") != data.password:
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة")
    if customer.get("verified") is not False:
        return {"verified": True, "status": "verified"}
    return {
        "verified": False,
        "status": str(customer.get("verification_status") or "not_requested"),
        "requested_at": customer.get("verification_requested_at") or "",
        "has_code": bool(customer.get("verification_code_hash")),
    }

UNLINK_ADMIN_PHONE = "784225716"  # رقم استقبال طلبات فك الربط (خدمة العملاء)


class DeviceUnlinkIn(BaseModel):
    phone: str
    password: str
    device_id: Optional[str] = None

@api.post("/public/customer/request-device-unlink")
async def public_request_device_unlink(data: DeviceUnlinkIn):
    """طلب العميل فك ربط حسابه من الجهاز السابق: يُرسل الطلب للإدارة فقط."""
    customer = await db.customers.find_one({"phone": data.phone})
    if not customer or customer.get("password") != data.password:
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة")
    bound = str(customer.get("bound_device") or "").strip()
    if not bound:
        return {"ok": True, "already_unbound": True,
                "message": "حسابك غير مرتبط بجهاز حالياً، يمكنك تسجيل الدخول مباشرة"}
    now = now_iso()
    msg = (
        f"طلب فك ربط الحساب من الجهاز\n"
        f"الاسم: {customer.get('name') or ''}\n"
        f"الهاتف: {customer.get('phone') or ''}\n"
        f"العنوان: {customer.get('address') or ''}\n"
        f"تاريخ ووقت الطلب: {now}"
    )
    if str(customer.get("device_unlink_status") or "") != "requested":
        # لا يُنشأ إشعار داخلي للإدارة: يُرسل الطلب كرسالة واتساب أو رسالة نصية إلى رقم خدمة العملاء
        await db.customers.update_one({"id": customer["id"]}, {"$set": {
            "device_unlink_status": "requested",
            "device_unlink_requested_at": now,
            "device_unlink_request_device": (data.device_id or "")[:120],
            "updated_at": now,
        }})
    admin_digits = "".join(ch for ch in str(UNLINK_ADMIN_PHONE) if ch.isdigit()).lstrip("0")
    admin_intl = ("967" + admin_digits) if (admin_digits and not admin_digits.startswith("967")) else admin_digits
    from urllib.parse import quote
    wa_url = f"https://wa.me/{admin_intl}?text={quote(msg)}" if admin_intl else ""
    sms_url = f"sms:+{admin_intl}?body={quote(msg)}" if admin_intl else ""
    return {"ok": True,
            "message": "تم تجهيز طلبك. أرسله للإدارة عبر واتساب أو رسالة نصية ليتم فك ربط حسابك من الجهاز السابق.",
            "request_message": msg,
            "admin_phone": UNLINK_ADMIN_PHONE,
            "whatsapp_url": wa_url,
            "sms_url": sms_url}

@api.get("/device-unlink-requests")
async def list_device_unlink_requests(user=Depends(require_perm("customers"))):
    """طلبات فك ربط الحساب من الجهاز المعلّقة."""
    items = await db.customers.find({
        "device_unlink_status": {"$in": ["requested", "approved"]},
    }).sort("device_unlink_requested_at", -1).limit(500).to_list(500)
    pending, done = [], []
    for c in items:
        row = {
            "id": c.get("id"), "name": c.get("name") or "", "phone": c.get("phone") or "",
            "address": c.get("address") or "",
            "requested_at": c.get("device_unlink_requested_at") or "",
            "bound_device": (c.get("bound_device") or "")[:60],
            "new_device": (c.get("device_unlink_request_device") or "")[:60],
            "status": c.get("device_unlink_status") or "",
        }
        if row["status"] == "approved":
            row["approved_at"] = c.get("device_unlink_approved_at") or ""
            row["generated_password"] = c.get("device_unlink_generated_password") or ""
            row["channel"] = c.get("device_unlink_channel") or ""
            done.append(row)
        else:
            pending.append(row)
    done = done[:50]
    return {"items": pending + done, "pending_count": len(pending)}

class DeviceUnlinkApproveIn(BaseModel):
    channel: Optional[str] = None

@api.post("/device-unlink-requests/{cid}/approve")
async def approve_device_unlink(cid: str, data: DeviceUnlinkApproveIn, user=Depends(require_perm("customers"))):
    """موافقة الإدارة: فك ربط الجهاز وإرسال رسالة للعميل عبر القناة المختارة."""
    channel = str(data.channel or "").strip().lower()
    if channel not in ("whatsapp", "sms"):
        raise HTTPException(status_code=400, detail="اختر قناة إرسال الرسالة: واتساب أو رسالة نصية")
    customer = await db.customers.find_one({"id": cid})
    if not customer:
        raise HTTPException(status_code=404, detail="الحساب غير موجود")
    if str(customer.get("device_unlink_status") or "") != "requested":
        raise HTTPException(status_code=400, detail="لا يوجد طلب فك ربط معلّق لهذا الحساب")
    old_device = customer.get("bound_device")
    now = now_iso()
    # كلمة مرور جديدة للأمان: تُلغى القديمة فوراً وتُرسل الجديدة للعميل
    new_password = await unique_random_password()
    await db.customers.update_one(
        {"id": cid},
        {"$set": {"bound_device": None, "bound_device_at": None,
                  "password": new_password,
                  "password_changed_at": now,
                  "password_changed_by": user.get("username"),
                  "password_change_reason": "device_unlink",
                  "device_unlink_status": "approved",
                  "device_unlink_approved_at": now,
                  "device_unlink_approved_by": user.get("username"),
                  "device_unlink_channel": channel,
                  "device_unlink_generated_password": new_password,
                  "updated_at": now},
         "$push": {"device_history": {"unbound_at": now, "unbound_by": user.get("username"), "was": old_device}}},
    )
    await audit_log(user, "approve_device_unlink", "customer", cid, None,
                    {"name": customer.get("name"), "channel": channel, "password_regenerated": True})
    await db.notifications.update_many({"category": "device_unlink_request", "ref_id": cid},
                                       {"$set": {"read": True, "read_at": now}})
    body = await _render_message_template("unbind_account", {
        "name": customer.get("name", ""), "phone": customer.get("phone", ""),
        "password": new_password, "company": COMPANY_NAME,
    })
    phone_digits = "".join(ch for ch in str(customer.get("phone") or "") if ch.isdigit()).lstrip("0")
    wa_phone = "967" + phone_digits if (phone_digits and not phone_digits.startswith("967")) else phone_digits
    from urllib.parse import quote
    wa_url = f"https://wa.me/{wa_phone}?text={quote(body)}" if channel == "whatsapp" and wa_phone else ""
    sms_url = f"sms:+{wa_phone}?body={quote(body)}" if channel == "sms" and wa_phone else ""
    return {"ok": True, "channel": channel, "phone": customer.get("phone"),
            "message": body, "password": new_password,
            "whatsapp_url": wa_url, "sms_url": sms_url}

@api.post("/device-unlink-requests/{cid}/resend")
async def resend_device_unlink_message(cid: str, data: DeviceUnlinkApproveIn, user=Depends(require_perm("customers"))):
    """إعادة إرسال رسالة فك الربط مع كلمة المرور الجديدة دون تغييرها."""
    channel = str(data.channel or "").strip().lower()
    if channel not in ("whatsapp", "sms"):
        raise HTTPException(status_code=400, detail="اختر قناة إرسال الرسالة: واتساب أو رسالة نصية")
    customer = await db.customers.find_one({"id": cid})
    if not customer:
        raise HTTPException(status_code=404, detail="الحساب غير موجود")
    if str(customer.get("device_unlink_status") or "") != "approved":
        raise HTTPException(status_code=400, detail="لم يتم فك ربط هذا الحساب بعد")
    now = now_iso()
    pwd = str(customer.get("device_unlink_generated_password") or "")
    await db.customers.update_one({"id": cid}, {"$set": {
        "device_unlink_channel": channel, "device_unlink_resent_at": now,
        "device_unlink_resent_by": user.get("username"), "updated_at": now,
    }})
    await audit_log(user, "resend_device_unlink_message", "customer", cid, None,
                    {"name": customer.get("name"), "channel": channel})
    body = await _render_message_template("unbind_account", {
        "name": customer.get("name", ""), "phone": customer.get("phone", ""),
        "password": pwd, "company": COMPANY_NAME,
    })
    phone_digits = "".join(ch for ch in str(customer.get("phone") or "") if ch.isdigit()).lstrip("0")
    wa_phone = "967" + phone_digits if (phone_digits and not phone_digits.startswith("967")) else phone_digits
    from urllib.parse import quote
    wa_url = f"https://wa.me/{wa_phone}?text={quote(body)}" if channel == "whatsapp" and wa_phone else ""
    sms_url = f"sms:+{wa_phone}?body={quote(body)}" if channel == "sms" and wa_phone else ""
    return {"ok": True, "channel": channel, "phone": customer.get("phone"),
            "message": body, "password": pwd,
            "whatsapp_url": wa_url, "sms_url": sms_url}
@api.post("/device-unlink-requests/{cid}/reject")
async def reject_device_unlink(cid: str, user=Depends(require_perm("customers"))):
    customer = await db.customers.find_one({"id": cid})
    if not customer:
        raise HTTPException(status_code=404, detail="الحساب غير موجود")
    now = now_iso()
    await db.customers.update_one({"id": cid}, {"$set": {
        "device_unlink_status": "rejected",
        "device_unlink_rejected_at": now,
        "device_unlink_rejected_by": user.get("username"),
        "updated_at": now,
    }})
    await db.notifications.update_many({"category": "device_unlink_request", "ref_id": cid},
                                       {"$set": {"read": True, "read_at": now}})
    await audit_log(user, "reject_device_unlink", "customer", cid, None, {"name": customer.get("name")})
    return {"ok": True}

@api.post("/public/card-order/request")
@idempotent_operation("public_card_order", "sales")
async def public_order(data: CardOrderRequest):
    if not data.idempotency_key.strip():
        raise HTTPException(status_code=400, detail="مفتاح الحماية مطلوب")
    customer = await db.customers.find_one({"phone": data.phone})
    if not customer:
        await db.card_order_attempts.insert_one({
            "id": str(uuid.uuid4()), "phone": data.phone, "status": "rejected_not_found",
            "reason": "العميل غير موجود", "created_at": now_iso(),
        })
        raise HTTPException(status_code=404, detail="لاتمتلك حساب بهذا الرقم، عليك بانشاء حساب أولاً")
    if customer.get("password") != data.password:
        raise HTTPException(status_code=401, detail="كلمة السر غير صحيحة")
    if customer.get("status") == "disabled":
        raise HTTPException(status_code=403, detail="الحساب معطل")
    cat = await db.card_categories.find_one({"id": data.category_id})
    if not cat: raise HTTPException(status_code=404, detail="الفئة غير موجودة")
    if is_balance_category(cat):
        raise HTTPException(status_code=400, detail="فئة رصيد مخصصة لتحويل الرصيد ولا يمكن طلبها ككرت")
    # Normalize recipient phone (keep only digits/+). If it equals sender's phone, treat as None.
    recipient = (data.recipient_phone or "").strip()
    if recipient:
        digits = "".join(ch for ch in recipient if ch.isdigit() or ch == "+")
        if len(digits) < 6:
            raise HTTPException(status_code=400, detail="رقم الهاتف المستلم غير صالح")
        recipient = digits
        if recipient == (customer.get("phone") or "").strip():
            recipient = ""  # same as sender; ignore
    recipient_customer = None
    if recipient:
        recipient_customer = await db.customers.find_one({"$or": [
            {"phone": recipient}, {"phone": recipient.lstrip("+")},
            {"phone": f"0{recipient}"}, {"phone": f"967{recipient}"},
        ]}, {"_id": 0, "id": 1, "name": 1, "phone": 1})
    recipient_name = (recipient_customer or {}).get("name") or ""
    # Pick price according to customer type (POS vs regular customer)
    ctype = str(customer.get("customer_type") or "customer").strip().lower()
    unit_price = cat.get("sale_price_pos") if ctype == "pos" else cat.get("sale_price_customer")
    if unit_price is None:
        unit_price = cat.get("sale_price", 0)
    total = _numeric_amount(unit_price, 0.0) * int(data.quantity)
    try:
        _ensure_customer_credit_limit(customer, total)
    except HTTPException:
        await db.card_order_attempts.insert_one({
            "id": str(uuid.uuid4()), "customer_id": customer["id"], "customer_name": customer["name"],
            "phone": customer["phone"], "category_id": data.category_id, "category_name": cat.get("name"),
            "quantity": data.quantity, "total": total, "status": "rejected_over_limit",
            "reason": "تجاوز السقف المسموح", "created_at": now_iso(),
        })
        raise HTTPException(status_code=400, detail=OVER_LIMIT_MSG)
    # Reserve NUMBERED cards ONLY. This endpoint never falls back to quantity stock.
    numbered_avail = await db.cards.count_documents({"category_id": data.category_id, "status": "available"})
    if numbered_avail < data.quantity:
        await db.card_order_attempts.insert_one({
            "id": str(uuid.uuid4()), "customer_id": customer["id"], "customer_name": customer["name"],
            "phone": customer["phone"], "category_id": data.category_id, "category_name": cat.get("name"),
            "quantity": data.quantity, "total": total, "status": "rejected_no_stock",
            "reason": "لا تتوفر كمية الكروت المطلوبة", "created_at": now_iso(),
        })
        raise HTTPException(status_code=400, detail="لا تتوفر كمية الكروت المطلوبة")

    cards_reserved = []
    numbered = await db.cards.find({"category_id": data.category_id, "status": "available"}).limit(data.quantity).to_list(data.quantity)
    for c in numbered:
        r = await db.cards.update_one({"id": c["id"], "status": "available"}, {"$set": {"status": "sold", "sold_at": now_iso(), "sold_to": customer["id"]}})
        if r.modified_count == 1:
            cards_reserved.append(c["number"])
    if len(cards_reserved) < data.quantity:
        # Race condition — someone else consumed cards concurrently. Rollback and reject.
        if cards_reserved:
            await db.cards.update_many({"number": {"$in": cards_reserved}}, {"$set": {"status": "available", "sold_at": None, "sold_to": None}})
        await db.card_order_attempts.insert_one({
            "id": str(uuid.uuid4()), "customer_id": customer["id"], "customer_name": customer["name"],
            "phone": customer["phone"], "category_id": data.category_id, "category_name": cat.get("name"),
            "quantity": data.quantity, "total": total, "status": "rejected_no_stock",
            "reason": "لا تتوفر كمية الكروت المطلوبة", "created_at": now_iso(),
        })
        raise HTTPException(status_code=400, detail="لا تتوفر كمية الكروت المطلوبة")

    number = (data.number or "").strip() or await next_gwd_number()
    # Create sale invoice
    sale_doc = {
        "id": str(uuid.uuid4()), "number": number, "type": "sale",
        "customer_id": customer["id"], "customer_name": customer["name"],
        "sale_type": "credit", "source": "public_order",
        "items": [{"category_id": data.category_id, "category_name": cat.get("name"),
                   "quantity": data.quantity, "price": unit_price,
                   "total": total, "card_numbers": cards_reserved, "use_numbered": True}],
        "subtotal": total, "discount": 0, "total": total, "paid": 0, "remaining": total,
        "notes": ("طلب عبر رابط طلب الكرت" + (f" — تحويل إلى: {recipient}" if recipient else "")),
        "recipient_phone": recipient or None, "recipient_name": recipient_name or None,
        "status": "active", "created_at": now_iso(), "operation_at": now_iso(),
        "idempotency_key": data.idempotency_key,
        "success": True, "cards": cards_reserved, "quantity_from_stock": 0,
        "message": "تم تنفيذ طلبك بنجاح",
    }
    order_doc = {
        "id": str(uuid.uuid4()), "number": number, "customer_id": customer["id"],
        "customer_name": customer["name"], "phone": customer["phone"],
        "category_id": data.category_id, "category_name": cat.get("name"),
        "quantity": data.quantity, "total": total, "cards": cards_reserved,
        "recipient_phone": recipient or None, "recipient_name": recipient_name or None,
        "quantity_stock_taken": 0,
        "status": "delivered", "created_at": now_iso(), "idempotency_key": data.idempotency_key,
    }
    sale_inserted = False
    order_inserted = False
    try:
        await db.sales.insert_one(sale_doc)
        sale_inserted = True
        balance_after = await _adjust_party_balance("customer", customer["id"], total, number, f"مبيعات إلكترونية - طلب كرت {number}")
        sale_doc["balance_after"] = balance_after
        await db.sales.update_one({"id": sale_doc["id"]}, {"$set": {"balance_after": balance_after}})
        await db.orders.insert_one(order_doc)
        order_inserted = True
        if cards_reserved:
            try:
                _ord_rows = await db.cards.find({"number": {"$in": cards_reserved}}, {"id": 1, "number": 1}).to_list(len(cards_reserved))
                await log_card_events(_ord_rows, "sold", None,
                                      {"sale_id": sale_doc.get("id"), "sale_number": sale_doc.get("number"),
                                       "customer_id": customer.get("id"), "customer_name": customer.get("name") or ""},
                                      f"طلب كرت من بوابة العميل {number}")
            except Exception as exc:
                logger.warning("card order event log failed: %s", exc)
    except Exception:
        await _remove_ledger_by_op("customer", customer["id"], number)
        if order_inserted:
            await db.orders.delete_one({"id": order_doc["id"]})
        if sale_inserted:
            await db.sales.delete_one({"id": sale_doc["id"]})
        await db.cards.update_many(
            {"number": {"$in": cards_reserved}, "sold_to": customer["id"]},
            {"$set": {"status": "available"}, "$unset": {"sold_at": "", "sold_to": ""}},
        )
        raise

    try:
        await db.card_order_attempts.insert_one({
            "id": str(uuid.uuid4()), "customer_id": customer["id"], "customer_name": customer["name"],
            "phone": customer["phone"], "category_id": data.category_id, "category_name": cat.get("name"),
            "quantity": data.quantity, "total": total, "cards": cards_reserved,
            "invoice_number": number, "recipient_phone": recipient or None,
            "recipient_name": recipient_name or None,
            "status": "success", "reason": "", "created_at": now_iso(),
        })
        notification_title = f"طلب كرت {number}"
        notification_message = await _render_message_template("card_order_notification", {
            "number": number,
            "amount": total,
            "account_name": customer.get("name", ""),
            "recipient_phone": recipient or "",
        })
        notification_details = {
            "operation": "card_order",
            "operation_id": sale_doc["id"],
            "customer_id": customer["id"],
            "amount": total,
            "account_name": customer.get("name", ""),
            "recipient_phone": recipient or None,
            "document": {
                "type": "sale",
                "sale": clean_doc(sale_doc),
                "customer": {
                    "id": customer.get("id"),
                    "name": customer.get("name", ""),
                    "phone": customer.get("phone", ""),
                    "customer_type": customer.get("customer_type") or "customer",
                    "balance": balance_after,
                },
            },
        }
        await notify(notification_title, notification_message, "success", user_id=None, details=notification_details)
        await notify_customer_account(customer["id"], notification_title, notification_message, "success", notification_details)
        # إشعار حساب المستلم إذا كان رقمه مرتبطاً بحساب في البوابة
        if recipient_customer and recipient_customer.get("id") and recipient_customer.get("id") != customer.get("id"):
            _rnums = [str(n) for n in (cards_reserved or []) if n]
            _rmsg = (f"من: {customer.get('name','')} — الفئة: {cat.get('name','')} — "
                     f"السعر: {_numeric_amount(unit_price, 0.0)} ريال — عدد الكروت: {int(data.quantity)}")
            if len(_rnums) == 1:
                _rmsg += f" — رقم الكرت: {_rnums[0]}"
            await notify_customer_account(recipient_customer["id"], "وصلك كرت", _rmsg, "success", {
                "category": "card_received", "card_numbers": _rnums,
                "category_name": cat.get("name") or "",
                "unit_price": _numeric_amount(unit_price, 0.0), "total": total,
                "quantity": int(data.quantity),
                "sender_name": customer.get("name") or "", "sender_phone": customer.get("phone") or "",
                "invoice_number": number, "popup": True,
            })
    except Exception as exc:
        logger.warning("public card order post-commit log/notification failed: %s", exc)
    return clean_doc(sale_doc)

@api.get("/public/card-order/categories")
async def public_categories(request: Request):
    items = await db.card_categories.find({"status": "active", "show_in_public": {"$ne": False}, "kind": {"$ne": "balance"}, "name": {"$ne": BALANCE_CATEGORY_NAME}}).to_list(500)
    result = []
    for c in items:
        numbered_avail = await db.cards.count_documents({"category_id": c["id"], "status": "available"})
        result.append({
            "id": c["id"], "name": c["name"],
            "sale_price": c.get("sale_price", 0),
            "sale_price_customer": c.get("sale_price_customer", c.get("sale_price", 0)),
            "sale_price_pos": c.get("sale_price_pos", c.get("sale_price", 0)),
            "available_numbered": numbered_avail,
        })
    return _etag_response(request, result, extra="public-categories")


@api.post("/public/card-order/my-orders")
async def public_my_orders(data: CardOrderHistoryIn):
    """Return the authenticated customer's past card orders, optionally within a date range.
    Auth is done via phone+password (same credentials used to place orders)."""
    customer = await db.customers.find_one({"phone": data.phone})
    if not customer:
        raise HTTPException(status_code=404, detail="لاتمتلك حساب بهذا الرقم")
    if customer.get("password") != data.password:
        raise HTTPException(status_code=401, detail="كلمة السر غير صحيحة")
    if customer.get("status") == "disabled":
        raise HTTPException(status_code=403, detail="الحساب معطل")

    query: Dict[str, Any] = {"customer_id": customer["id"]}
    if data.start or data.end:
        query["$expr"] = mongo_business_date_expr(data.start, data.end)
    docs = await db.orders.find(query).sort("created_at", -1).limit(500).to_list(500)
    return [clean_doc(o) for o in docs]


@api.post("/public/card-order/my-transfers")
async def public_my_transfers(data: CardOrderHistoryIn):
    """Return transfers where the authenticated customer is the sender."""
    customer = await db.customers.find_one({"phone": data.phone})
    if not customer:
        raise HTTPException(status_code=404, detail="لاتمتلك حساب بهذا الرقم")
    if customer.get("password") != data.password:
        raise HTTPException(status_code=401, detail="كلمة السر غير صحيحة")
    if customer.get("status") == "disabled":
        raise HTTPException(status_code=403, detail="الحساب معطل")

    query: Dict[str, Any] = {"sender_id": customer["id"], "status": {"$ne": "cancelled"}}
    if data.start or data.end:
        query["$expr"] = mongo_business_date_expr(data.start, data.end)
    docs = await db.transfers.find(query).sort("created_at", -1).limit(500).to_list(500)
    return [_public_transfer_view(t) for t in docs]


@api.post("/public/card-order/my-payment-confirmations")
async def public_my_payment_confirmations(data: CardOrderHistoryIn):
    """Return the authenticated customer's payment-verification history.

    This is a read-only, customer-scoped view. It deliberately excludes the
    pasted client SMS and any Gateway secret material; it exposes only the
    operation reference, amount, receiving-account type, current result, and
    a review reason when the verification failed or needs manual review.
    """
    customer = await _verify_public_customer(data.phone, data.password)
    await _expire_unresolved_payment_confirmations(customer_id=customer["id"])
    query: Dict[str, Any] = {"customer_id": customer["id"]}
    if data.start or data.end:
        query["$expr"] = mongo_business_date_expr(data.start, data.end)
    docs = await db.payment_verifications.find(query).sort("created_at", -1).limit(500).to_list(500)

    bank_ids = {doc.get("bank_account_id") for doc in docs if doc.get("bank_account_id")}
    bank_map: Dict[str, Dict[str, Any]] = {}
    if bank_ids:
        banks = await db.bank_accounts.find({"id": {"$in": list(bank_ids)}}).to_list(len(bank_ids))
        bank_map = {bank.get("id"): bank for bank in banks if bank.get("id")}
    message_ids = {doc.get("review_message_id") for doc in docs if doc.get("review_message_id")}
    gateway_message_map: Dict[str, Dict[str, Any]] = {}
    if message_ids:
        messages = await db.payment_gateway_messages.find({"id": {"$in": list(message_ids)}}, {"id": 1, "sms_text": 1}).to_list(len(message_ids))
        gateway_message_map = {message.get("id"): message for message in messages if message.get("id")}

    status_labels = {
        "pending": "قيد المراجعة",
        "matched": "تم التحقق — بانتظار التسجيل",
        "posting": "جارٍ تسجيل سند القبض",
        "manual_review": "قيد المراجعة اليدوية",
        "approved": "نجاح العملية",
        "rejected": "فشل العملية",
    }
    result = []
    for doc in docs:
        stored_status = str(doc.get("status") or "pending").lower()
        status = stored_status
        effect = str(doc.get("financial_effect") or "none").lower()
        bank = bank_map.get(doc.get("bank_account_id")) or {}
        provider_type = str(bank.get("provider_type") or "bank").lower()
        payment_type = "محفظة إلكترونية" if provider_type == "wallet" else "حساب بنكي"
        operation_reference = doc.get("payment_reference") or doc.get("client_transaction_id") or doc.get("retry_transaction_id") or doc.get("id")
        successful = status == "approved" and effect == "posted"
        gateway_message = gateway_message_map.get(doc.get("review_message_id")) or {}
        failure_reason = doc.get("review_note") or doc.get("review_reason") or ""
        status_label = status_labels.get(status, status)
        if status == "approved" and not successful:
            status_label = "تمت الموافقة — بانتظار التسجيل"
        result.append(clean_doc({
            "id": doc.get("id"),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "operation": operation_reference,
            "amount": _safe_amount(doc.get("amount")),
            "bank_account_id": doc.get("bank_account_id"),
            "bank_name": bank.get("bank_name") or "حساب السداد",
            "bank_account_type": payment_type,
            "status": status,
            "status_label": status_label,
            "success": successful,
            "failure_reason": failure_reason,
            "failure_code": doc.get("failure_code", ""),
            "gateway_message_text": gateway_message.get("sms_text", ""),
            "verification_method": doc.get("verification_method") or ("reference" if doc.get("client_payment_reference") else "sms_text"),
            "financial_effect": effect,
            "receipt_number": doc.get("receipt_number"),
            "payment_reference": doc.get("payment_reference") or doc.get("client_transaction_id") or doc.get("retry_transaction_id"),
            "balance_after": doc.get("balance_after"),
            "retryable": status == "rejected",
        }))
    return result


class QuickRechargeListIn(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None

@api.post("/admin/quick-recharge/list")
async def admin_quick_recharge_list(data: QuickRechargeListIn, user=Depends(require_perm("receipts"))):
    """List previous quick-recharge operations (stored as receipts with channel=admin_quick_recharge)."""
    query: Dict[str, Any] = {"channel": "admin_quick_recharge", "status": "active"}
    if data.start or data.end:
        query["$expr"] = mongo_business_date_expr(data.start, data.end)
    docs = await db.receipts.find(query).sort("created_at", -1).limit(500).to_list(500)
    return [clean_doc(r) for r in docs]

class StatementIn(BaseModel):
    phone: str
    password: str
    start: Optional[str] = None  # YYYY-MM-DD
    end: Optional[str] = None    # YYYY-MM-DD

@api.post("/public/card-order/statement")
async def public_customer_statement(data: StatementIn):
    """Return customer + ledger entries for the customer portal statement print.
    Auth via phone+password. Optional date range with correct opening balance."""
    customer = await db.customers.find_one({"phone": data.phone})
    if not customer:
        raise HTTPException(status_code=404, detail="لاتمتلك حساب بهذا الرقم")
    if customer.get("password") != data.password:
        raise HTTPException(status_code=401, detail="كلمة السر غير صحيحة")
    if customer.get("status") == "disabled":
        raise HTTPException(status_code=403, detail="الحساب معطل")

    base_q: Dict[str, Any] = {"party_type": "customer", "party_id": customer["id"]}
    opening_balance = 0.0
    start_utc, _ = business_range_bounds(data.start, data.end)

    if start_utc:
        parsed_created = {"$convert": {"input": "$created_at", "to": "date", "onError": None, "onNull": None}}
        prior = await db.ledger.aggregate([
            {"$match": {**base_q, "$expr": {"$lt": [parsed_created, start_utc]}}},
            {"$group": {"_id": None, "debit": {"$sum": {"$ifNull": ["$debit", 0]}}, "credit": {"$sum": {"$ifNull": ["$credit", 0]}}}},
        ]).to_list(1)
        if prior:
            opening_balance = float(prior[0].get("debit", 0) or 0) - float(prior[0].get("credit", 0) or 0)

    q = {**base_q, "$expr": mongo_business_date_expr(data.start, data.end)} if (data.start or data.end) else base_q
    entries_raw = await db.ledger.find(q).sort("created_at", 1).to_list(10000)

    entries: List[Dict[str, Any]] = []
    if start_utc and opening_balance != 0:
        entries.append({
            "id": "opening", "op_number": "-",
            "description": f"رصيد افتتاحي حتى {data.start}",
            "debit": opening_balance if opening_balance > 0 else 0,
            "credit": abs(opening_balance) if opening_balance < 0 else 0,
            "balance": opening_balance,
            "created_at": business_timestamp(data.start),
        })
    # Re-compute running balance across the returned window starting from opening_balance
    running = opening_balance
    for e in entries_raw:
        running += (e.get("debit") or 0) - (e.get("credit") or 0)
        d = clean_doc(e)
        d["balance"] = running
        entries.append(d)

    c = clean_doc(customer)
    c.pop("password", None)
    return {
        "customer": c,
        "entries": entries,
        "range": {"start": data.start, "end": data.end},
        "opening_balance": opening_balance,
        "closing_balance": running,
    }

@api.get("/orders")
async def list_orders(user=Depends(require_perm("card_orders"))):
    items = await db.orders.find().sort("created_at", -1).limit(1000).to_list(1000)
    return [clean_doc(o) for o in items]


# ================= WEB PUSH =================
class PushSubscriptionIn(BaseModel):
    subscription: Dict[str, Any]


@api.get("/push/public-key")
async def push_public_key():
    return {"public_key": os.getenv("VAPID_PUBLIC_KEY", ""), "configured": bool(os.getenv("VAPID_PUBLIC_KEY") and os.getenv("VAPID_PRIVATE_KEY") and _webpush)}


@api.post("/push/subscribe")
async def push_subscribe(data: PushSubscriptionIn, user=Depends(get_current_user)):
    sub = data.subscription or {}
    endpoint = (sub.get("endpoint") or "").strip()
    keys = sub.get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=400, detail="اشتراك الإشعارات غير صالح")
    await db.push_subscriptions.update_one(
        {"endpoint": endpoint},
        {"$set": {"id": str(uuid.uuid4()), "endpoint": endpoint, "subscription": sub, "user_id": user.get("id"), "role": user.get("role", "staff"), "updated_at": now_iso()}, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True, "subscription_status": "subscribed"}


@api.get("/push/status")
async def push_status(user=Depends(get_current_user)):
    count = await db.push_subscriptions.count_documents({"user_id": user.get("id")})
    latest = await db.push_subscriptions.find_one(
        {"user_id": user.get("id")},
        {"_id": 0, "updated_at": 1},
        sort=[("updated_at", -1)],
    )
    return {
        "configured": bool(os.getenv("VAPID_PUBLIC_KEY") and os.getenv("VAPID_PRIVATE_KEY") and _webpush),
        "subscribed": count > 0,
        "devices": count,
        "updated_at": (latest or {}).get("updated_at"),
    }


class PushTestIn(BaseModel):
    title: str = "Push test"
    message: str = "Push delivery test"

@api.post("/push/test")
async def push_test(data: PushTestIn, user=Depends(get_current_user)):
    _test_title = data.title.strip()[:120]
    _test_body = data.message.strip()[:500]
    result = await _send_web_push(_test_title, _test_body, "test", user_id=user.get("id"))
    fcm_started = False
    try:
        settings, _ = await _app_channel_settings()
        if settings.get("fcm_enabled", True):
            asyncio.create_task(_send_fcm(_test_title, _test_body, "test", user.get("id"), {"category": "test"}))
            fcm_started = True
    except Exception:
        pass
    return {"ok": bool(result.get("sent")) or fcm_started, "result": result, "fcm": fcm_started}


@api.delete("/push/subscribe")
async def push_unsubscribe(endpoint: str, user=Depends(get_current_user)):
    await db.push_subscriptions.delete_one({"endpoint": endpoint, "user_id": user.get("id")})
    return {"ok": True}


# ================= NOTIFICATIONS =================
# ================= NOTIFICATION TARGETS =================
# Where a notification points, so tapping it opens the operation itself
# (a receipt/invoice/transfer) or the screen that owns the event.
_DOCUMENT_OPERATIONS = {
    "receipt": "receipt",
    "public_receipt": "receipt",
    "sale": "sale",
    "sales": "sale",
    "electronic_sale": "sale",
    "public_direct_card_purchase": "sale",
    "public_card_order": "sale",
    "purchase": "purchase",
    "purchase_return": "purchase",
    "transfer": "transfer",
    "free_card": "free_card",
    "subscriber_transfer": "transfer",
    "quick_recharge": "transfer",
    "cash_transfer": "transfer",
}
_TARGET_LABELS = {
    "receipt": "سند قبض",
    "sale": "فاتورة بيع",
    "purchase": "فاتورة شراء",
    "transfer": "سند تحويل",
    "free_card": "كرت مجاني",
}
_TARGET_TITLE_HINTS = (
    ("كرت مجاني", "free_card"),
    ("مشتريات", "purchase"),
    ("مبيعات", "sale"),
    ("فاتورة", "sale"),
    ("سند قبض", "receipt"),
    ("سند صرف", "receipt"),
    ("حافز", "receipt"),
    ("تحويل", "transfer"),
    ("تغذية رصيد", "transfer"),
)
_TARGET_DOC_NUMBER = _re.compile(r"([A-Z]{2,6}\s?-?\d{3,9})")

async def _notification_target(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a notification to the operation it announces.

    Returns {kind, route, label, document, entity_id}. `kind` is one of
    document / screen / account_request / stock_alert / none.
    Older notifications carry no reference at all, so the document number is
    also read from the title/message and looked up in the documents collections.
    """
    doc = doc or {}
    details = doc.get("details") or {}
    # Tapping a phone notification must open the notification text itself (the
    # same thing that happens when a row is tapped inside the notifications
    # screen) - never a document editor.
    focus_route = f"/admin-notifications?focus={doc.get('id')}" if doc.get("id") else "/admin-notifications"
    category = str(doc.get("category") or details.get("category") or "").strip()
    operation = str(details.get("operation") or doc.get("operation") or "").strip().lower()
    title = str(doc.get("title") or "")
    text = f"{title} {doc.get('message') or ''}"
    ref = doc.get("ref_id") or details.get("ref_id")
    if category == "account_request" or operation == "account_request":
        return {"kind": "account_request", "route": "/unverified/", "label": "طلب توثيق حساب"}
    if category == "device_unlink_request" or operation == "device_unlink_request":
        return {"kind": "screen", "route": focus_route, "label": "طلب فك ربط الحساب من الجهاز",
                "entity_id": details.get("customer_id") or doc.get("ref_id") or ""}
    if category == "password_reset_request" or operation == "password_reset_request":
        return {"kind": "screen", "route": focus_route, "label": "طلب استعادة كلمة المرور",
                "entity_id": details.get("customer_id") or doc.get("ref_id") or ""}
    if category == "stock_alert" or operation == "stock_alert":
        cid = doc.get("category_id") or details.get("category_id") or ""
        _ = cid  # kept for backwards compatibility of stored notifications
        return {"kind": "stock_alert", "route": focus_route, "label": "تنبيه مخزون"}
    customer_id = details.get("customer_id") or doc.get("customer_id") or ""
    entity_id = details.get("operation_id") or details.get("ref_id") or ref
    document = _DOCUMENT_OPERATIONS.get(operation)
    embedded = details.get("document")
    if not document and isinstance(embedded, dict):
        for key, kind in (("sale", "sale"), ("purchase", "purchase"), ("receipt", "receipt"), ("transfer", "transfer")):
            snapshot = embedded.get(key)
            if isinstance(snapshot, dict) and snapshot.get("id"):
                document = kind
                entity_id = entity_id or snapshot.get("id")
                break
    if not document:
        for hint, kind in _TARGET_TITLE_HINTS:
            if hint in text:
                document = kind
                break
    if document and not entity_id:
        match = _TARGET_DOC_NUMBER.search(text)
        if match:
            number = match.group(1).replace(" ", "")
            collections = {
                "receipt": db.receipts,
                "sale": db.sales,
                "purchase": db.purchases,
                "transfer": db.transfers,
            }
            found = await collections[document].find_one({"number": number}, {"id": 1})
            if not found:
                for kind, collection in collections.items():
                    found = await collection.find_one({"number": number}, {"id": 1})
                    if found:
                        document = kind
                        break
            if found:
                entity_id = found.get("id")
    if document and entity_id:
        route = {
            "receipt": f"/receipts?focus={entity_id}",
            "sale": f"/sales/{entity_id}/edit",
            "purchase": f"/purchases/{entity_id}/edit",
            "transfer": f"/transfers?focus={entity_id}",
            "free_card": f"/free-cards?focus={entity_id}",
        }[document]
        return {
            "kind": "document",
            "document": document,
            "entity_id": entity_id,
            "route": focus_route,
            "label": _TARGET_LABELS.get(document, "العملية"),
        }
    if document:
        route = {"receipt": "/receipts", "sale": "/sales", "purchase": "/purchases", "transfer": "/transfers"}[document]
        return {"kind": "screen", "route": focus_route, "label": _TARGET_LABELS.get(document, "العملية")}
    if operation in ("card_order", "payment_verification", "public_card_order_attempt"):
        return {"kind": "screen", "route": focus_route, "label": "طلبات الكروت"}
    if operation in ("customer_message", "broadcast"):
        return {"kind": "screen", "route": focus_route, "label": "الإشعارات"}
    if "حظر" in title:
        return {"kind": "screen", "route": focus_route, "label": "الأرقام المحظورة"}
    if customer_id:
        return {"kind": "screen", "route": focus_route, "label": "حساب العميل"}
    return {"kind": "none", "route": focus_route, "label": "إشعار"}

@api.get("/notifications/watch")
async def watch_notifications(since: Optional[str] = None, limit: int = 20, user=Depends(get_current_user)):
    """Lightweight feed for the Android background watcher (app closed).

    Returns what a staff phone must show while the app is not running: system
    notifications, new account registration requests and stock alerts that just
    appeared. `since` is an ISO cursor kept by the device.
    """
    try:
        size = max(1, min(int(limit or 20), 50))
    except (TypeError, ValueError):
        size = 20
    notification_settings, _ = await _app_channel_settings()
    if not notification_settings.get("enabled", True) or not notification_settings.get("in_app_enabled", True):
        return {"server_time": now_iso(), "items": []}
    items: List[Dict[str, Any]] = []
    query: Dict[str, Any] = {"customer_id": {"$exists": False}, "kind": {"$ne": "admin_broadcast"}}
    if since:
        query["created_at"] = {"$gt": since}
    docs = await db.notifications.find(query).sort("created_at", -1).limit(size).to_list(size)
    for doc in docs:
        if doc.get("category") == "account_request" and not notification_settings.get("account_requests_enabled", True):
            continue
        target = await _notification_target(doc)
        items.append({
            "id": doc.get("id"),
            "title": doc.get("title") or "إشعار التطبيق",
            "message": doc.get("message") or "",
            "category": doc.get("category") or "general",
            "created_at": doc.get("created_at") or "",
            "kind": target.get("kind") or "none",
            "route": target.get("route") or "",
        })
    if notification_settings.get("stock_alerts_enabled", True):
        stock_query: Dict[str, Any] = {}
        if since:
            stock_query["created_at"] = {"$gt": since}
        events = await db.stock_alert_events.find(stock_query).sort("created_at", -1).limit(size).to_list(size)
        for event in events:
            target = await _notification_target({"category": "stock_alert", "category_id": event.get("category_id")})
            items.append({
                "id": event.get("id"),
                "title": event.get("title") or "تنبيه مخزون",
                "message": event.get("message") or "",
                "category": "stock_alert",
                "created_at": event.get("created_at") or "",
                "kind": target.get("kind") or "none",
                "route": target.get("route") or "",
            })
    items.sort(key=lambda item: item.get("created_at") or "")
    return {"server_time": now_iso(), "items": items[:size]}


@api.get("/api/notifications/watch")
async def watch_notifications_compat(since: Optional[str] = None, limit: int = 20,
                                     user=Depends(get_current_user)):
    """مسار توافقي: بعض إصدارات التطبيق تستدعي المسار مع بادئة /api مكرّرة
    (https://gawad.cc/api/api/notifications/watch) فيعود 404 وتتوقف إشعارات
    الطلبات على الجهاز. هذا المسار يعيد نفس النتيجة دون تحديث التطبيق."""
    return await watch_notifications(since=since, limit=limit, user=user)


def _gwd_etag(payload: Any, extra: str = "") -> str:
    """بصمة مختصرة للاستجابة تُستخدم مع If-None-Match."""
    import hashlib, json as _json
    try:
        raw = _json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(payload)
    return 'W/"' + hashlib.md5((raw + "|" + extra).encode("utf-8")).hexdigest()[:24] + '"'


def _etag_response(request, payload: Any, extra: str = ""):
    """يُرجع 304 بجسم فارغ إذا لم تتغير البيانات — توفير حقيقي في البيانات المنقولة."""
    import json as _json
    from fastapi.encoders import jsonable_encoder
    etag = _gwd_etag(payload, extra)
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if (request.headers.get("if-none-match") or "").strip() == etag:
        return Response(status_code=304, headers=headers)
    return Response(
        content=_json.dumps(jsonable_encoder(payload), ensure_ascii=False).encode("utf-8"),
        media_type="application/json",
        headers=headers,
    )


@api.get("/notifications")
async def list_notifications(request: Request, user=Depends(get_current_user)):
    # Admin/staff inbox: system notifications only. Exclude per-customer docs
    # (broadcast messages targeted at customers carry a customer_id / admin_broadcast kind).
    items = await db.notifications.find({
        "customer_id": {"$exists": False},
        "kind": {"$ne": "admin_broadcast"},
    }).sort("created_at", -1).limit(200).to_list(200)
    ids = [item.get("id") for item in items if item.get("id")]
    explicit_reads = await db.notification_reads.find({
        "user_id": user.get("id"), "notification_id": {"$in": ids}
    }).to_list(len(ids) or 1)
    read_ids = {row.get("notification_id") for row in explicit_reads}
    seen_at = user.get("notifications_seen_at") or ""
    async def _pack(item: dict) -> dict:
        doc = clean_doc(item)
        doc["read"] = doc.get("id") in read_ids or bool(seen_at and doc.get("created_at", "") <= seen_at)
        try:
            doc["target"] = await _notification_target(item)
        except Exception:
            doc["target"] = {"kind": "none", "route": "/", "label": "إشعار"}
        return doc

    # حساب الأهداف بالتوازي بدلاً من التسلسل (كان السبب الرئيسي في البطء)
    result = await asyncio.gather(*[_pack(item) for item in items])
    payload = list(result)
    return _etag_response(request, payload, extra=str(user.get("id") or ""))

@api.get("/notifications/summary")
async def notifications_summary(request: Request, user=Depends(get_current_user)):
    """Per-user unread counters for the header bells.
    - general_unread: system notifications created after this user last opened the
      notifications page (stored per-user as `notifications_seen_at`). New items make
      it reappear; opening the page clears it — independently for every user.
    - request_unread: pending account-creation requests (shared task queue).
    """
    seen_at = user.get("notifications_seen_at") or ""
    general_q: Dict[str, Any] = {
        "customer_id": {"$exists": False},
        "kind": {"$ne": "admin_broadcast"},
        "category": {"$ne": "account_request"},
    }
    if seen_at:
        general_q["created_at"] = {"$gt": seen_at}
    general_unread = await db.notifications.count_documents(general_q)
    unverified_accounts = await db.customers.count_documents(
        {"verified": False, "status": {"$ne": "deleted"},
         "verification_status": {"$in": ["requested", "awaiting_code"]}}
    )
    unread_requests = await db.notifications.count_documents(
        {"category": "account_request", "read": False}
    )
    request_unread = max(unverified_accounts, unread_requests)
    payload = {"general_unread": general_unread, "request_unread": request_unread}
    return _etag_response(request, payload, extra=str(user.get("id") or ""))


@api.get("/admin/operation-number-audit")
async def operation_number_audit(limit: int = 60, user=Depends(get_current_user)):
    """قراءة فقط: أرقام العمليات المصروفة، وأيها بلا مستند مالي (رقابة على التسلسل)."""
    if (user.get("role") or "") not in ("admin", "supervisor", "manager"):
        raise HTTPException(status_code=403, detail="غير مصرح بالوصول لهذا التقرير.")
    limit = max(1, min(int(limit or 60), 300))
    rows = await db.operation_number_audit.find({}).sort("value", -1).limit(limit).to_list(limit)
    items = []
    for row in rows:
        num = row.get("number")
        found = None
        for coll, field in (("ledger", "op_number"), ("sales", "number"),
                            ("orders", "number"), ("card_order_attempts", "invoice_number")):
            hit = await db[coll].find_one({field: num}, {"_id": 0, "id": 1})
            if hit:
                found = coll
                break
        if not found:
            hit = await db.notifications.find_one({"details.send_number": num}, {"_id": 0, "id": 1})
            if hit:
                found = "free_card"
        items.append({
            "number": num,
            "allocated_at": row.get("allocated_at"),
            "caller": row.get("caller"),
            "document": found or "MISSING",
        })
    missing = [x["number"] for x in items if x["document"] == "MISSING"]
    return {"count": len(items), "missing_count": len(missing), "missing": missing, "items": items}

@api.post("/notifications/mark-seen")
async def notifications_mark_seen(user=Depends(get_current_user)):
    """Marks all current system notifications as seen for THIS user (per-user state,
    persisted in the DB) so the general bell counter clears immediately and does not
    reappear on refresh/re-login until a newer notification arrives."""
    await db.users.update_one({"id": user["id"]}, {"$set": {"notifications_seen_at": now_iso()}})
    return {"ok": True}

@api.post("/notifications/{nid}/read")
async def mark_read(nid: str, user=Depends(get_current_user)):
    if not await db.notifications.find_one({"id": nid}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="الإشعار غير موجود")
    await db.notification_reads.update_one(
        {"user_id": user.get("id"), "notification_id": nid},
        {"$set": {"read_at": now_iso()}, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True}

@api.post("/notifications/mark-category-read")
async def mark_category_read(category: str, user=Depends(get_current_user)):
    """Marks all unread notifications of a category as read.
    Persists in DB so the counter does not come back after logout or refresh
    unless new items arrive."""
    if category not in ("account_request", "user_lock", "general"):
        raise HTTPException(status_code=400, detail="فئة غير صحيحة")
    r = await db.notifications.update_many(
        {"category": category, "read": False},
        {"$set": {"read": True, "read_at": now_iso(), "read_by": user.get("username")}},
    )
    return {"ok": True, "updated": r.modified_count}


# ================= STOCK ALERTS (header notifications bell) =================
STOCK_ALERT_WATCH_SECONDS = 300
STOCK_ALERT_BASELINE_KEY = "__initialized__"
_stock_alert_task: Optional[asyncio.Task] = None


async def _compute_stock_alerts() -> list:
    """Low-stock alerts shared by the header bell and the background watcher.
    Uses the SAME per-category threshold logic as the dashboard (numbered vs
    quantity, independent thresholds)."""
    cats = await db.card_categories.find().to_list(500)
    alerts = []
    for c in cats:
        if is_balance_category(c):
            continue
        avail = await db.cards.count_documents({"category_id": c["id"], "status": "available"})
        stock = await db.stock.find_one({"category_id": c["id"]})
        qty_avail = (stock or {}).get("total", 0) - (stock or {}).get("sold", 0) if stock else 0
        combined = c.get("low_stock_threshold", 20) or 0
        thr_num = c.get("low_stock_numbered")
        thr_qty = c.get("low_stock_quantity")
        if thr_num is None: thr_num = combined
        if thr_qty is None: thr_qty = combined
        if thr_num and thr_num > 0 and avail <= thr_num:
            alerts.append({
                "type": "numbered", "category_id": c["id"], "category_name": c.get("name", ""),
                "available": avail, "threshold": thr_num,
            })
        if thr_qty and thr_qty > 0 and max(0, qty_avail) <= thr_qty:
            alerts.append({
                "type": "quantity", "category_id": c["id"], "category_name": c.get("name", ""),
                "available": max(0, qty_avail), "threshold": thr_qty,
            })
    alerts.sort(key=lambda x: (x["available"], x["type"]))
    for alert in alerts:
        alert["message"] = await _render_message_template("stock_alerts", {
            "category_name": alert.get("category_name", ""),
            "available": alert.get("available", 0),
            "threshold": alert.get("threshold", 0),
        })
        alert["key"] = f"{alert['type']}:{alert['category_id']}"
    return alerts


async def _evaluate_stock_alerts_once() -> int:
    """Record ONE event the moment an alert appears; never while it stays low.
    The first ever pass only establishes the baseline so a fresh install does
    not flood the phones with alerts that already exist."""
    if not await _message_channel_enabled("stock_alerts", "in_app"):
        return 0
    alerts = await _compute_stock_alerts()
    current = {alert["key"]: alert for alert in alerts}
    rows = await db.stock_alert_state.find().to_list(2000)
    baseline_done = any(row.get("key") == STOCK_ALERT_BASELINE_KEY for row in rows)
    active = {row.get("key") for row in rows if row.get("key") and row.get("key") != STOCK_ALERT_BASELINE_KEY}
    now = now_iso()
    created = 0
    for key, alert in current.items():
        if key in active:
            continue
        await db.stock_alert_state.update_one(
            {"key": key},
            {"$set": {"key": key, "category_id": alert.get("category_id"), "alert_type": alert.get("type"),
                      "available": alert.get("available"), "threshold": alert.get("threshold"),
                      "category_name": alert.get("category_name"), "updated_at": now}},
            upsert=True,
        )
        if not baseline_done:
            continue
        doc = {
            "id": str(uuid.uuid4()), "key": key, "title": "تنبيه مخزون",
            "message": alert.get("message") or f"{alert.get('category_name', '')}: المتوفر {alert.get('available', 0)}",
            "type": "warning", "category": "stock_alert", "category_id": alert.get("category_id"),
            "category_name": alert.get("category_name"), "available": alert.get("available"),
            "threshold": alert.get("threshold"), "alert_type": alert.get("type"),
            "read": False, "created_at": now,
        }
        await db.stock_alert_events.insert_one(dict(doc))
        created += 1
        notification_settings, _ = await _app_channel_settings()
        if notification_settings.get("web_push_enabled", True):
            asyncio.create_task(_send_web_push(doc["title"], doc["message"], "warning", None))
        if notification_settings.get("fcm_enabled", True):
            # إشعار فوري للإدارة حتى والتطبيق مغلق
            asyncio.create_task(_send_fcm(doc["title"], doc["message"], "warning", None,
                                          {"category": "stock_alert", "notification_id": doc["id"],
                                           "category_id": doc.get("category_id"), "available": doc.get("available"),
                                           "threshold": doc.get("threshold")}))
    stale = [key for key in active if key not in current]
    if stale:
        await db.stock_alert_state.delete_many({"key": {"$in": stale}})
    if not baseline_done:
        await db.stock_alert_state.update_one(
            {"key": STOCK_ALERT_BASELINE_KEY},
            {"$set": {"key": STOCK_ALERT_BASELINE_KEY, "updated_at": now}},
            upsert=True,
        )
        logger.info("Stock alert watcher baseline established (%d active alerts)", len(current))
    return created


async def _stock_alert_watch_loop() -> None:
    while True:
        try:
            await _evaluate_stock_alerts_once()
        except Exception as exc:
            logger.warning("stock alert watcher failed: %s", exc)
        await asyncio.sleep(STOCK_ALERT_WATCH_SECONDS)


@api.get("/stock/alerts")
async def stock_alerts(user=Depends(get_current_user)):
    """Low-stock alerts for the header notifications bell."""
    if not await _message_channel_enabled("stock_alerts", "in_app"):
        return {"count": 0, "alerts": []}
    alerts = await _compute_stock_alerts()
    return {"count": len(alerts), "alerts": alerts}


# ================= AUDIT =================
@api.get("/audit")
async def list_audit(
    start: Optional[str] = None,
    end: Optional[str] = None,
    q: Optional[str] = None,
    user=Depends(require_perm("users")),
):
    """List audit entries. Optional YYYY-MM-DD `start`/`end` filter (Yemen TZ +03:00)
    and free-text `q` search over username/action/entity."""
    mongo_q: Dict[str, Any] = {}
    if start or end:
        mongo_q["$expr"] = mongo_business_date_expr(start, end)
    if q and q.strip():
        rx = {"$regex": _re.escape(q.strip()), "$options": "i"}
        mongo_q["$or"] = [{"username": rx}, {"action": rx}, {"entity": rx}]
    items = await db.audit_logs.find(mongo_q).sort("created_at", -1).limit(1000).to_list(1000)
    return [clean_doc(a) for a in items]


# ================= REPORTS =================
@api.get("/reports/dashboard")
async def dashboard_stats(date: Optional[str] = None, user=Depends(get_current_user)):
    # Use Yemen local date so operations from 00:00 to 23:59 local time count
    # in the correct day regardless of UTC crossovers.
    if date:
        try:
            now_yem = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=APP_TIMEZONE)
        except ValueError:
            raise HTTPException(status_code=422, detail="صيغة التاريخ غير صالحة")
    else:
        now_yem = _server_now()
    today = now_yem.date().isoformat()
    month_start = now_yem.date().replace(day=1).isoformat()
    if now_yem.month == 12:
        next_month = now_yem.date().replace(year=now_yem.year + 1, month=1, day=1)
    else:
        next_month = now_yem.date().replace(month=now_yem.month + 1, day=1)
    month_end = (next_month - timedelta(days=1)).isoformat()

    async def sum_total(collection, query):
        rows = await collection.aggregate([
            {"$match": query},
            {"$group": {"_id": None, "value": {"$sum": {"$ifNull": ["$total", 0]}}}},
        ]).to_list(1)
        return float(rows[0]["value"]) if rows else 0.0

    sales_today = await sum_total(db.sales, {"status": "active", "$expr": mongo_business_date_expr(today, today)})
    sales_month = await sum_total(db.sales, {"status": "active", "$expr": mongo_business_date_expr(month_start, month_end)})
    purchases_total = await sum_total(db.purchases, {"status": "active"})
    customers = await db.customers.find().to_list(10000)
    suppliers = await db.suppliers.find().to_list(10000)
    customer_debts = sum(max(0, c.get("balance", 0)) for c in customers if c.get("customer_type") != "pos")
    # Custom account types keep their operational base (`customer_type=pos`)
    # for financial workflows, but must not be counted in the native POS KPI.
    pos_debts = sum(c.get("balance", 0) for c in customers if _is_native_pos_customer(c))
    supplier_debts = sum(max(0, -s.get("balance", 0)) for s in suppliers)
    cards_available = await db.cards.count_documents({"status": "available"})
    cards_sold = await db.cards.count_documents({"status": "sold"})
    cards_used = await db.cards.count_documents({"status": "used"})
    users_count = await db.users.count_documents({})
    # inventory value + low-stock alerts (reuse same loop, zero extra queries).
    # Numbered vs quantity are tracked INDEPENDENTLY using per-category thresholds
    # `low_stock_numbered` and `low_stock_quantity`. Falls back to
    # `low_stock_threshold` when either specific threshold is unset.
    cats = await db.card_categories.find().to_list(500)
    inventory_value = 0
    low_stock_alerts = []
    for c in cats:
        avail = await db.cards.count_documents({"category_id": c["id"], "status": "available"})
        stock = await db.stock.find_one({"category_id": c["id"]})
        qty_avail = (stock or {}).get("total", 0) - (stock or {}).get("sold", 0) if stock else 0
        inventory_value += (avail + max(0, qty_avail)) * c.get("purchase_price", 0)
        combined = c.get("low_stock_threshold", 20) or 0
        thr_num = c.get("low_stock_numbered")
        thr_qty = c.get("low_stock_quantity")
        if thr_num is None: thr_num = combined
        if thr_qty is None: thr_qty = combined
        if thr_num and thr_num > 0 and avail <= thr_num:
            low_stock_alerts.append({
                "type": "numbered",
                "category_id": c["id"], "category_name": c.get("name", ""),
                "available": avail, "threshold": thr_num,
            })
        if thr_qty and thr_qty > 0 and max(0, qty_avail) <= thr_qty:
            low_stock_alerts.append({
                "type": "quantity",
                "category_id": c["id"], "category_name": c.get("name", ""),
                "available": max(0, qty_avail), "threshold": thr_qty,
            })
    low_stock_alerts.sort(key=lambda x: (x["available"], x["type"]))
    # recent
    recent_sales = await db.sales.find().sort("created_at", -1).limit(5).to_list(5)
    recent_receipts = await db.receipts.find().sort("created_at", -1).limit(5).to_list(5)
    recent_orders = await db.orders.find().sort("created_at", -1).limit(5).to_list(5)
    chart_start = (now_yem.date() - timedelta(days=13)).isoformat()
    chart = await db.sales.aggregate([
        {"$match": {"status": "active", "$expr": mongo_business_date_expr(chart_start, today)}},
        {"$group": {"_id": {"$dateToString": {"date": {"$convert": {"input": "$created_at", "to": "date", "onError": None, "onNull": None}}, "format": "%Y-%m-%d", "timezone": "+03:00"}}, "value": {"$sum": {"$ifNull": ["$total", 0]}}}},
        {"$sort": {"_id": 1}},
        {"$project": {"_id": 0, "date": "$_id", "value": 1}},
    ]).to_list(14)
    return {
        "sales_today": sales_today,
        "sales_month": sales_month,
        "purchases_total": purchases_total,
        "customer_debts": customer_debts,
        "pos_debts": pos_debts,
        "supplier_debts": supplier_debts,
        "inventory_value": inventory_value,
        "cards_available": cards_available,
        "cards_sold": cards_sold,
        "cards_used": cards_used,
        "low_stock_alerts": low_stock_alerts,
        "customers_count": len(customers),
        "suppliers_count": len(suppliers),
        "users_count": users_count,
        "recent_sales": [clean_doc(s) for s in recent_sales],
        "recent_receipts": [clean_doc(r) for r in recent_receipts],
        "recent_orders": [clean_doc(o) for o in recent_orders],
        "pending_register_requests": await db.register_requests.count_documents({"status": "pending"}),
        "chart": chart,
    }

@api.get("/reports/sales")
async def report_sales(start: Optional[str] = None, end: Optional[str] = None, limit: int = 2000, offset: int = 0, user=Depends(require_perm("reports"))):
    q: Dict[str, Any] = {"status": "active"}
    if start and end:
        q["$expr"] = mongo_business_date_expr(start, end)
    limit = min(max(int(limit or 2000), 1), 5000)
    offset = max(int(offset or 0), 0)
    items = await db.sales.find(q).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    return [clean_doc(s) for s in items]

@api.get("/reports/sales-by-customer")
async def report_sales_by_customer(
    start: Optional[str] = None,
    end: Optional[str] = None,
    customer_id: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 5000,
    user=Depends(require_perm("reports")),
):
    """Return sales rows and totals grouped by the actual linked customer."""
    # Read active sales first and apply the official business-date filter in
    # Python as a compatibility path for legacy documents whose created_at is
    # stored as a string rather than a BSON Date.
    query: Dict[str, Any] = {"status": {"$ne": "cancelled"}}
    if customer_id:
        query["$or"] = [{"customer_id": customer_id}, {"party_id": customer_id}]
    limit = min(max(int(limit or 5000), 1), 10000)
    raw_sales = await db.sales.find(query).sort("created_at", -1).limit(limit).to_list(limit)
    sales = [sale for sale in raw_sales if timestamp_in_business_range(sale.get("created_at"), start, end)] if (start or end) else raw_sales
    customers = await db.customers.find({}, {"_id": 0, "id": 1, "name": 1, "phone": 1, "customer_type": 1}).to_list(10000)
    by_id = {c.get("id"): c for c in customers}
    term = (q or "").strip().lower()
    grouped: Dict[str, Dict[str, Any]] = {}
    rows: List[Dict[str, Any]] = []
    for sale in sales:
        linked = by_id.get(sale.get("customer_id")) or {}
        name = sale.get("customer_name") or linked.get("name") or "نقدي"
        phone = sale.get("customer_phone") or linked.get("phone") or ""
        if term and term not in f"{name} {phone}".lower():
            continue
        key = sale.get("customer_id") or "cash"
        total = float(sale.get("total") or 0)
        group = grouped.setdefault(key, {
            "customer_id": sale.get("customer_id"),
            "customer_name": name,
            "customer_phone": phone,
            "customer_type": linked.get("customer_type") or sale.get("customer_type") or "customer",
            "sales_count": 0,
            "total": 0.0,
        })
        group["sales_count"] += 1
        group["total"] += total
        rows.append({
            **clean_doc(sale),
            "customer_name": name,
            "customer_phone": phone,
            "customer_type": group["customer_type"],
        })
    summary = sorted(grouped.values(), key=lambda item: item["total"], reverse=True)
    return {
        "items": rows,
        "summary": summary,
        "count": len(rows),
        "total": sum(item["total"] for item in summary),
        "range": {"start": start, "end": end},
    }

@api.get("/reports/purchases")
async def report_purchases(start: Optional[str] = None, end: Optional[str] = None, limit: int = 2000, offset: int = 0, user=Depends(require_perm("reports"))):
    q: Dict[str, Any] = {"status": "active"}
    if start and end:
        q["$expr"] = mongo_business_date_expr(start, end)
    limit = min(max(int(limit or 2000), 1), 5000)
    offset = max(int(offset or 0), 0)
    items = await db.purchases.find(q).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    return [clean_doc(p) for p in items]

@api.get("/reports/customer-debts")
async def report_customer_debts(user=Depends(require_perm("reports"))):
    items = await db.customers.find().to_list(10000)
    return [clean_doc(c) for c in items if c.get("balance", 0) > 0]

@api.get("/reports/supplier-debts")
async def report_supplier_debts(user=Depends(require_perm("reports"))):
    items = await db.suppliers.find().to_list(10000)
    # المورد دائن عندما نكون مدينين له (رصيد سالب). نعرض المديونية كقيمة موجبة.
    return [{**clean_doc(s), "balance": -s.get("balance", 0)} for s in items if s.get("balance", 0) < 0]


# ================= AUTOMATIC MESSAGE TEMPLATES =================
MESSAGE_TEMPLATE_DEFAULTS = {
    "free_card_send": {
        "name": "إرسال كرت مجاني",
        "description": "الرسالة التي تُرسل للمستلم عند إهدائه كرتاً مجانياً.",
        "variables": ["name", "category", "card_number", "company"],
        "text": "مرحباً {{name}} 👋\n\nتم إرسال كرت {{category}} إليك مجاناً من {{company}}.\nرقم الكرت: {{card_number}}\n\nنتمنى لك تجربة موفقة.",
    },
    "account_request": {
        "name": "طلب توثيق حساب",
        "description": "إشعار الإدارة عند وصول طلب توثيق حساب جديد.",
        "variables": ["name", "phone", "address", "account_type"],
        "text": "طلب توثيق حساب\nالاسم: {{name}}\nالهاتف: {{phone}}\nالعنوان: {{address}}\nالنوع: {{account_type}}",
    },
    "user_lock": {
        "name": "حظر مستخدم",
        "description": "إشعار الإدارة عند حظر مستخدم بعد محاولات دخول فاشلة.",
        "variables": ["username", "attempts"],
        "text": "تم حظر حساب المستخدم {{username}} بسبب تجاوز {{attempts}} محاولات دخول فاشلة.",
    },
    "stock_alerts": {
        "name": "تنبيهات المخزون",
        "description": "العنوان العام لتنبيهات انخفاض مخزون الكروت.",
        "variables": ["category_name", "available", "threshold"],
        "text": "تنبيه مخزون: {{category_name}}\nالمتاح: {{available}}\nالحد: {{threshold}}",
    },
    "welcome_account": {
        "name": "ترحيب الحساب الجديد",
        "description": "الرسالة التي تُرسل عند الموافقة على طلب إنشاء حساب عميل.",
        "variables": ["name", "phone", "password", "company"],
        "text": "مرحباً {{name}} 👋\n\nتم إنشاء حسابك بنجاح في {{company}}.\nرقم الهاتف: {{phone}}\nكلمة المرور:\n{{password}}\n\nيمكنك الآن تسجيل الدخول وطلب الكروت مباشرة.",
    },
    "password_reset": {
        "name": "تعديل كلمة المرور",
        "description": "الرسالة التي تُرسل بعد تعديل كلمة مرور العميل.",
        "variables": ["name", "phone", "password", "company"],
        "text": "مرحباً {{name}} 👋\n\nتم تعديل كلمة المرور الخاصة بحسابك في {{company}}.\nرقم الهاتف: {{phone}}\nكلمة المرور الجديدة:\n{{password}}\n\nيرجى تسجيل الدخول باستخدام البيانات الجديدة.",
    },
    "unblock_account": {
        "name": "فك حظر الحساب",
        "description": "الرسالة التي تُرسل بعد فك حظر رقم العميل.",
        "variables": ["name", "phone", "company"],
        "text": "مرحباً {{name}} 👋\n\nتم فك الحظر عن حسابك في {{company}}.\nرقم الهاتف: {{phone}}\n\nيمكنك الآن تسجيل الدخول إلى حسابك.",
    },
    "sale_notification": {"name": "إشعار فاتورة المبيعات", "description": "إشعار فعلي بعد حفظ فاتورة مبيعات.", "variables": ["number", "amount", "account_name", "invoice_type", "paid", "remaining", "description", "balance_after"], "text": "تم تسجيل فاتورة مبيعات رقم {{number}} في حسابك.\nالحساب: {{account_name}}\nإجمالي الفاتورة: {{amount}}\nالمدفوع: {{paid}}\nالمتبقي: {{remaining}}\nالنوع: {{invoice_type}}\nالبيان: {{description}}\nالرصيد بعد العملية: {{balance_after}}"},
    "sale_success_whatsapp": {"name": "رسالة نجاح حفظ فاتورة المبيعات", "description": "النص الذي يرسل من نافذة نجاح حفظ الفاتورة عبر WhatsApp.", "variables": ["number", "account_name", "details", "amount", "discount", "total", "paid", "remaining", "balance_after"], "text": "من شبكة جواد نت اللاسلكية\n\nعليكم فاتورة رقم: {{number}}\nالحساب: {{account_name}}\nتفاصيل الفاتورة:\n{{details}}\n\nمبلغ الفاتورة: {{total}}\nالخصم: {{discount}}\nالمدفوع: {{paid}}\nالمتبقي: {{remaining}}\nالرصيد بعد العملية: {{balance_after}}"},
    "purchase_notification": {"name": "إشعار فاتورة المشتريات", "description": "إشعار فعلي بعد حفظ فاتورة مشتريات.", "variables": ["number", "amount", "account_name", "invoice_type"], "text": "فاتورة مشتريات رقم {{number}}\nالمبلغ: {{amount}}\nالحساب: {{account_name}}\nالنوع: {{invoice_type}}"},
    "voucher_notification": {"name": "إشعار السندات", "description": "إشعار فعلي بعد حفظ سند قبض أو صرف.", "variables": ["number", "amount", "account_name", "voucher_type", "description", "balance_after"], "text": "تم تسجيل {{voucher_type}} في حسابك.\nرقم السند: {{number}}\nالمبلغ: {{amount}}\nالحساب: {{account_name}}\nالبيان: {{description}}\nالرصيد بعد العملية: {{balance_after}}"},
    "voucher_success_whatsapp": {"name": "رسالة نجاح حفظ السند", "description": "النص الذي يرسل من نافذة نجاح حفظ السند عبر WhatsApp.", "variables": ["kind", "number", "amount", "description", "balance_after"], "text": "من شبكة جواد نت اللاسلكية\n\n{{kind}} سند رقم: {{number}}\nمبلغ السند: {{amount}}\nتفاصيل السند:\n{{description}}\n\nالرصيد بعد العملية: {{balance_after}}"},
    "subscriber_transfer_notification": {"name": "إشعار تحويل المشترك", "description": "إشعار فعلي بعد تحويل رصيد بين مشتركين.", "variables": ["amount", "sender_name", "recipient_name", "number"], "text": "تحويل لمشترك\nالمبلغ: {{amount}}\nالمرسل: {{sender_name}}\nالمستلم: {{recipient_name}}\nرقم العملية: {{number}}"},
    "quick_recharge_notification": {"name": "إشعار تحويل الرصيد", "description": "إشعار فعلي بعد تحويل الرصيد من الصندوق.", "variables": ["amount", "recipient_name", "number"], "text": "تحويل رصيد\nالمبلغ: {{amount}}\nالحساب المستلم: {{recipient_name}}\nرقم العملية: {{number}}"},
    "card_order_notification": {"name": "إشعار شراء الكروت", "description": "إشعار فعلي بعد تنفيذ طلب شراء كروت.", "variables": ["number", "amount", "account_name", "recipient_phone"], "text": "طلب كرت رقم {{number}}\nالمبلغ: {{amount}}\nالحساب: {{account_name}}\nرقم المستلم: {{recipient_phone}}"},
    "account_verified_confirmation": {"name": "تأكيد توثيق الحساب", "description": "الرسالة التي تُرسل للعميل عند الموافقة على توثيق حسابه من البوابة.", "variables": ["name", "phone", "password", "company", "portal_url", "support_phone"], "text": "مرحباً {{name}}\n\nتم توثيق حسابك بنجاح في {{company}}.\nرقم الحساب: {{phone}}\nكلمة المرور: {{password}}\n\nيمكنك الآن الدخول إلى بوابة العميل وشراء الكروت:\n{{portal_url}}\n\nللدعم والتواصل: {{support_phone}}\n\n{{company}}"},
    "unbind_account": {"name": "فك ربط الجهاز", "description": "رسالة فعلية عند فك ربط جهاز العميل مع كلمة مرور جديدة.", "variables": ["name", "phone", "password", "company"], "text": "مرحباً {{name}} 👋\n\nتم فك ربط جهازك السابق عن حسابك في {{company}}.\nرقم الهاتف: {{phone}}\nكلمة المرور الجديدة:\n{{password}}\n\nيمكنك الآن تسجيل الدخول من جهازك الجديد باستخدام كلمة المرور الجديدة، وسيتم ربطه تلقائياً."},
    "payment_request": {
        "name": "طلب التسديد",
        "description": "قالب طلب التسديد مع المديونية والمبلغ المطلوب وبيانات السداد.",
        "variables": ["name", "balance", "amount", "company", "bank_details"],
        "text": "مرحباً {{name}}\n\nإجمالي المديونية: {{balance}}\nالمبلغ المطلوب سداده: {{amount}}\n\n{{bank_details}}\n\n{{company}}",
    },
}

class MessageTemplateIn(BaseModel):
    text: str

async def _compose_auto_message(text: str) -> str:
    settings = await db.settings.find_one({"key": "app_settings"}) or {}
    body = (text or "").strip()
    prefix = str(settings.get("auto_message_prefix") or "").strip()
    suffix = str(settings.get("auto_message_suffix") or "").strip()
    while prefix and body.startswith(prefix):
        body = body[len(prefix):].lstrip()
    while suffix and body.endswith(suffix):
        body = body[:-len(suffix)].rstrip()
    return "\n\n".join(x for x in (prefix, body, suffix) if x)

_PASSWORD_LINE_LABELS = ("كلمة المرور الجديدة", "كلمة المرور", "رقم الهاتف", "اسم المستخدم")


def _password_on_own_line(text: str) -> str:
    """Render "كلمة المرور: 1234" as "كلمة المرور:\n1234" so phones can select it easily."""
    import re as _regex
    out = text or ""
    for label in _PASSWORD_LINE_LABELS:
        out = _regex.sub(rf"({label})\s*:\s*([^\n]+)", rf"\1:\n\2", out)
    return out


async def _render_message_template(key: str, values: Dict[str, Any]) -> str:
    event_config = await _message_event_config(key)
    if not event_config["enabled"]:
        return ""
    defaults = MESSAGE_TEMPLATE_DEFAULTS.get(key) or {"text": ""}
    doc = await db.message_templates.find_one({"key": key})
    template = (doc or {}).get("text") or defaults.get("text", "")
    allowed = set(defaults.get("variables", []))
    for name, value in values.items():
        if name in allowed:
            template = template.replace("{{" + name + "}}", str(value if value is not None else ""))
    template = _password_on_own_line(template)
    return await _compose_auto_message(template)

@api.get("/message-templates")
async def list_message_templates(user=Depends(require_perm("settings", "free_cards"))):
    docs = await db.message_templates.find().to_list(100)
    custom = {d.get("key"): d for d in docs}
    result = []
    for key, default in MESSAGE_TEMPLATE_DEFAULTS.items():
        result.append({"key": key, **default, "text": (custom.get(key) or {}).get("text") or default["text"], "default_text": default["text"], "customized": bool((custom.get(key) or {}).get("text"))})
    return result

@api.put("/message-templates/{key}")
async def update_message_template(key: str, data: MessageTemplateIn, user=Depends(require_perm("settings"))):
    if key not in MESSAGE_TEMPLATE_DEFAULTS:
        raise HTTPException(status_code=404, detail="القالب غير موجود")
    text = (data.text or "").strip()
    if len(text) > 5000:
        raise HTTPException(status_code=400, detail="نص القالب طويل جداً")
    if text:
        await db.message_templates.update_one(
            {"key": key},
            {"$set": {"key": key, "text": text, "updated_at": now_iso(), "updated_by": user.get("username")}},
            upsert=True,
        )
    else:
        await db.message_templates.delete_one({"key": key})
    return {"ok": True, "key": key, "text": text or MESSAGE_TEMPLATE_DEFAULTS[key]["text"], "customized": bool(text)}


# ================= REGISTER REQUESTS =================
@api.get("/customers/unverified")
async def list_unverified_customers(user=Depends(require_perm("customers"))):
    """قائمة العملاء غير الموثّقين (حسابات أُنشئت تلقائياً من بوابة العميل)."""
    items = await db.customers.find({"verified": False}).sort("created_at", -1).limit(1000).to_list(1000)
    rows = []
    for c in items:
        rows.append({
            "id": c.get("id"), "name": c.get("name") or "", "phone": c.get("phone") or "",
            "address": c.get("address") or "",
            "requested_type": c.get("requested_type") or c.get("customer_type") or "customer",
            "origin": c.get("origin") or "", "created_at": c.get("created_at") or "",
            "verification_status": c.get("verification_status") or "not_requested",
            "verification_requested_at": c.get("verification_requested_at") or "",
            "balance": _numeric_amount(c.get("balance"), 0.0), "status": c.get("status") or "active",
        })
    return {"items": rows, "count": len(rows)}


class VerifyCustomerIn(BaseModel):
    customer_type: str = "customer"
    credit_limit: float = 0
    note: Optional[str] = None


@api.post("/customers/{cid}/verify")
async def verify_customer(cid: str, data: VerifyCustomerIn, user=Depends(require_perm("customers"))):
    """توثيق حساب غير موثّق: تحديد النوع النهائي والسقف."""
    c = await db.customers.find_one({"id": cid})
    if not c:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    if c.get("verified") is False:
        raise HTTPException(status_code=400, detail="لا يتم التوثيق مباشرة. استخدم طلب التوثيق ثم أرسل رمز التوثيق للعميل.")
    ctype = (data.customer_type or "customer").strip().lower()
    if ctype not in {"customer", "pos"}:
        raise HTTPException(status_code=400, detail="نوع الحساب غير صحيح")
    limit = max(_numeric_amount(data.credit_limit, 0.0), 0.0)
    note = (data.note or "").strip()
    upd = {"verified": True, "customer_type": ctype, "credit_limit": limit,
           "verified_at": now_iso(), "verified_by": user.get("username"), "updated_at": now_iso()}
    if note:
        upd["notes"] = ((c.get("notes") or "") + " | " + note).strip(" |")
    await db.customers.update_one({"id": cid}, {"$set": upd})
    await audit_log(user, "verify_customer", "customer", cid, None,
                    {"name": c.get("name"), "customer_type": ctype, "credit_limit": limit})
    _vmsg = (f"مرحباً {c.get('name','')}، تم توثيق حسابك في شبكة جواد نت اللاسلكية"
             + (f" بسقف {limit} ريال." if limit else "."))
    try:
        await notify_customer_account(cid, "تم توثيق حسابك", _vmsg, "success",
                                      {"category": "account_verified"})
    except Exception:
        pass
    digits = "".join(ch for ch in (c.get("phone") or "") if ch.isdigit() or ch == "+")
    return {"ok": True, "whatsapp": {"phone": digits, "message": _vmsg}}


@api.post("/customers/{cid}/reject-verification")
async def reject_verification(cid: str, user=Depends(require_perm("customers"))):
    """رفض حساب غير موثّق: تعطيله دون حذف للحفاظ على السجل."""
    c = await db.customers.find_one({"id": cid})
    if not c:
        raise HTTPException(status_code=404, detail="العميل غير موجود")
    await db.customers.update_one({"id": cid}, {"$set": {
        "status": "disabled", "verified": False, "rejected_at": now_iso(),
        "rejected_by": user.get("username"), "updated_at": now_iso()}})
    await audit_log(user, "reject_unverified_customer", "customer", cid, None, {"name": c.get("name")})
    return {"ok": True}


@api.get("/register-requests")
async def list_register_requests(user=Depends(require_perm("customers"))):
    """طلبات توثيق الحساب: طلبات التسجيل القديمة المعلّقة + حسابات البوابة غير الموثّقة."""
    items = await db.register_requests.find({"status": "pending"}).sort("created_at", -1).to_list(1000)
    out = [clean_doc(r) for r in items]
    unverified = await db.customers.find({
        "verified": False,
        "status": {"$ne": "deleted"},
        "verification_status": {"$in": ["requested", "awaiting_code"]},
    }).sort("verification_requested_at", -1).to_list(1000)
    for c in unverified:
        out.append({
            "id": c.get("id"),
            "full_name": c.get("name") or "",
            "phone": c.get("phone") or "",
            "address": c.get("address") or "",
            "account_type": "unverified",
            "credit_limit": _customer_credit_limit(c),
            "status": "pending",
            "created_at": c.get("created_at"),
            "verified": False,
            "kind": "unverified_account",
        })
    return out

class ApproveRegisterIn(BaseModel):
    credit_limit: float = Field(default=0, ge=0)
    customer_type: Optional[str] = None
    password: Optional[str] = None

class ApproveRegisterIn(BaseModel):
    # يجب اختيار قناة الإرسال صراحةً قبل إنشاء رمز التوثيق وإرساله.
    channel: Optional[str] = None

@api.post("/register-requests/{rid}/approve")
async def approve_register(rid: str, data: ApproveRegisterIn, user=Depends(require_perm("customers"))):
    """موافقة إدارية على طلب التوثيق وإنشاء رمز 6 أرقام دون توثيق قبل إدخاله."""
    cust = await db.customers.find_one({"id": rid})
    if not cust:
        raise HTTPException(status_code=404, detail="الحساب غير موجود")
    if cust.get("verified") is not False:
        raise HTTPException(status_code=400, detail="الحساب موثّق مسبقاً")
    if str(cust.get("verification_status") or "") not in {"requested", "awaiting_code"}:
        raise HTTPException(status_code=400, detail="لم يطلب العميل توثيق الحساب بعد")
    channel = str(data.channel or "").strip().lower()
    if channel not in ("whatsapp", "sms"):
        raise HTTPException(status_code=400, detail="اختر قناة إرسال رمز التوثيق: واتساب أو رسالة نصية")
    otp = f"{secrets.randbelow(1000000):06d}"
    now = now_iso()
    otp_hash = hashlib.sha256(f"{JWT_SECRET}:{cust['id']}:{otp}".encode("utf-8")).hexdigest()
    await db.customers.update_one({"id": rid}, {"$set": {
        "verification_status": "awaiting_code", "verification_code_hash": otp_hash,
        "verification_code_channel": channel, "verification_code_attempts": 0,
        "verification_code_created_at": now, "verification_approved_at": now,
        "verification_approved_by": user.get("username"), "updated_at": now,
    }})
    phone_digits = "".join(ch for ch in str(cust.get("phone") or "") if ch.isdigit())
    wa_phone = phone_digits.lstrip("0")
    if wa_phone and not wa_phone.startswith("967"):
        wa_phone = "967" + wa_phone
    body = f"شبكة جواد نت : رمز توثيق حسابك\n{otp}"
    from urllib.parse import quote
    wa_url = f"https://wa.me/{wa_phone}?text={quote(body)}" if channel == "whatsapp" and wa_phone else ""
    sms_url = f"sms:+{wa_phone}?body={quote(body)}" if channel == "sms" and wa_phone else ""
    await audit_log(user, "approve_verification_request", "customer", rid, None,
                    {"channel": channel, "phone": cust.get("phone")})
    return {"ok": True, "status": "awaiting_code", "channel": channel,
            "phone": cust.get("phone"), "message": body,
            "whatsapp_url": wa_url, "sms_url": sms_url}

@api.post("/register-requests/{rid}/reject")
async def reject_register(rid: str, user=Depends(require_perm("customers"))):
    cust = await db.customers.find_one({"id": rid})
    if cust and cust.get("verified") is False:
        await db.customers.update_one({"id": rid}, {
            "$inc": {"verification_reject_count": 1},
            "$set": {"verification_status": "rejected", "verification_rejected_at": now_iso(),
                     "verification_rejected_by": user.get("username")},
        })
        await audit_log(user, "reject_customer_verification", "customer", rid, None, {"name": cust.get("name")})
        await db.notifications.update_many({"category": "account_request", "ref_id": rid}, {"$set": {"read": True}})
        return {"ok": True}
    await db.register_requests.update_one({"id": rid}, {"$set": {"status": "rejected", "rejected_at": now_iso()}})
    return {"ok": True}


# ================= USER LOCK / DEVICE MGMT (ADMIN) =================
@api.post("/users/{uid}/unlock")
async def user_unlock(uid: str, user=Depends(require_perm("users"))):
    u = await db.users.find_one({"id": uid})
    if not u: raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    await db.users.update_one({"id": uid}, {"$set": {"failed_attempts": 0, "locked_until": None, "unlocked_at": now_iso(), "unlocked_by": user.get("username")}})
    await audit_log(user, "unlock", "user", uid)
    return {"ok": True}

@api.post("/users/{uid}/reset-attempts")
async def user_reset_attempts(uid: str, user=Depends(require_perm("users"))):
    await db.users.update_one({"id": uid}, {"$set": {"failed_attempts": 0}})
    await audit_log(user, "reset_attempts", "user", uid)
    return {"ok": True}

@api.post("/users/{uid}/unbind-device")
async def user_unbind_device(uid: str, user=Depends(require_perm("users"))):
    u = await db.users.find_one({"id": uid})
    if not u: raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    await db.users.update_one({"id": uid}, {"$unset": {"bound_device": "", "bound_device_at": ""}, "$set": {"unbound_at": now_iso(), "unbound_by": user.get("username")}})
    await audit_log(user, "unbind_device", "user", uid)
    return {"ok": True}


# ================= BLOCK MGMT =================
@api.get("/public-blocks")
async def list_blocks(user=Depends(require_perm("customers"))):
    items = await db.public_blocks.find().to_list(1000)
    return [clean_doc(b) for b in items]

@api.post("/public-blocks/{phone}/unblock")
async def unblock(phone: str, user=Depends(require_perm("customers"))):
    await db.public_blocks.update_one({"phone": phone}, {"$set": {"failed": 0, "blocked_until": None, "unblocked_at": now_iso(), "unblocked_by": user.get("username")}})
    await audit_log(user, f"فك الحظر: {phone}", "customer", phone)
    # WhatsApp URL
    from urllib.parse import quote
    cust = await db.customers.find_one({"phone": phone})
    name = (cust or {}).get("name", "")
    phone_digits = "".join(ch for ch in phone if ch.isdigit()).lstrip("0")
    wa_phone = "967" + phone_digits if (phone_digits and not phone_digits.startswith("967")) else phone_digits
    body = await _render_message_template("unblock_account", {
        "name": name, "phone": phone, "company": COMPANY_NAME,
    })
    wa_url = f"https://wa.me/{wa_phone}?text={quote(body)}" if wa_phone and await _message_channel_enabled("unblock_account", "whatsapp") and body else ""
    return {"ok": True, "whatsapp_url": wa_url}


# ================= RESET DATA =================
class ResetDataIn(BaseModel):
    username: str
    password: str
    confirm: bool = False

@api.post("/settings/reset-data")
async def reset_data(data: ResetDataIn, user=Depends(require_perm("settings"))):
    if not data.confirm:
        raise HTTPException(status_code=400, detail="يجب التأكيد")
    verify = await db.users.find_one({"username": data.username})
    if not verify or not verify_password(data.password, verify.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="بيانات الاعتماد غير صحيحة")
    if verify.get("role") != "admin":
        raise HTTPException(status_code=403, detail="يتطلب صلاحية المدير")
    # Wipe business and operational data while preserving users, settings, and
    # card category definitions. Categories are configuration/master data; the
    # cards and stock collections below are cleared, so retained categories
    # correctly reopen with zero available stock until new cards are added.
    # Keep this list explicit so backup metadata, configuration, and category
    # definitions cannot be removed accidentally.
    collections_to_wipe = [
        "customers", "suppliers", "cards", "stock",
        "stock_ops", "sales", "purchases", "receipts", "expenses", "ledger",
        "transfers", "orders", "notifications", "notification_reads",
        "audit_logs", "register_requests", "card_order_attempts", "public_blocks", "statement_imports", "card_pdf_previews",
        "incentive_earnings", "payment_requests", "operation_claims",
        "push_subscriptions",
    ]
    for c in collections_to_wipe:
        await db[c].delete_many({})
    # Reset GWD counter
    await db.settings.update_one({"key": "gwd_sequence"}, {"$set": {"value": 0}}, upsert=True)
    await audit_log(user, "reset_all_data", "system", "", None, {"by": data.username})
    return {"ok": True, "message": "تم مسح البيانات التشغيلية مع إبقاء فئات الكروت"}


# ================= BACKUP =================
@api.get("/backup/export")
async def backup_export(user=Depends(require_perm("backup"))):
    from fastapi.encoders import jsonable_encoder
    collections = ["customers","suppliers","bank_accounts","cashboxes","card_categories","cards","stock","stock_ops","sales","purchases","receipts","ledger","orders","notifications","audit_logs","register_requests","card_order_attempts","public_blocks","statement_imports","card_pdf_previews","users","settings"]
    def _deep(v):
        if isinstance(v, dict):
            return {k: _deep(x) for k, x in v.items() if k != "_id"}
        if isinstance(v, list):
            return [_deep(x) for x in v]
        return v
    dump = {}
    for c in collections:
        docs = await db[c].find().to_list(50000)
        dump[c] = [_deep(clean_doc(d)) for d in docs]
    dump["_exported_at"] = now_iso()
    return jsonable_encoder(dump, custom_encoder={bytes: lambda b: b.decode(errors="replace")})

class BackupRestoreIn(BaseModel):
    data: Dict[str, Any]

@api.post("/backup/restore")
async def backup_restore(payload: BackupRestoreIn, user=Depends(require_perm("backup"))):
    # Snapshot current before restore
    snapshot_id = str(uuid.uuid4())
    snapshot = {}
    collections = ["customers","suppliers","bank_accounts","cashboxes","card_categories","cards","stock","stock_ops","sales","purchases","receipts","ledger","orders","notifications","audit_logs","statement_imports","card_pdf_previews"]
    for c in collections:
        docs = await db[c].find().to_list(50000)
        snapshot[c] = [clean_doc(d) for d in docs]
    await db.backup_snapshots.insert_one({"id": snapshot_id, "data": snapshot, "created_at": now_iso(), "reason": "pre_restore"})
    # Wipe & restore
    data = payload.data
    for c in collections:
        if c in data:
            await db[c].delete_many({})
            if data[c]:
                await db[c].insert_many(data[c])
    await audit_log(user, "restore_backup", "system", snapshot_id)
    return {"ok": True, "snapshot_id": snapshot_id}


# ================= AUTOMATED CLOUD BACKUP =================
BACKUP_COLLECTIONS = [
    "customers","suppliers","bank_accounts","cashboxes","card_categories","cards","stock","stock_ops","sales","purchases",
    "receipts","ledger","orders","notifications","audit_logs","register_requests",
    "card_order_attempts","public_blocks","statement_imports","card_pdf_previews","users","settings","files",
]

async def _build_backup_snapshot() -> Dict[str, Any]:
    from fastapi.encoders import jsonable_encoder
    def _deep(v):
        if isinstance(v, dict):
            return {k: _deep(x) for k, x in v.items() if k != "_id"}
        if isinstance(v, list):
            return [_deep(x) for x in v]
        return v
    dump: Dict[str, Any] = {}
    for c in BACKUP_COLLECTIONS:
        docs = await db[c].find().to_list(100000)
        dump[c] = [_deep(clean_doc(d)) for d in docs]
    dump["_exported_at"] = now_iso()
    dump["_company"] = COMPANY_NAME
    return jsonable_encoder(dump, custom_encoder={bytes: lambda b: b.decode(errors="replace")})

async def _run_backup_job(trigger: str = "manual") -> Dict[str, Any]:
    """Create a snapshot, gzip-compress, upload to object storage, save metadata,
    and (best-effort) email the download link to the configured backup_email."""
    snapshot = await _build_backup_snapshot()
    raw = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    gz = gzip.compress(raw, compresslevel=6)

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    file_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    storage_path = f"{APP_NAME}/backups/{day}/{file_id}.json.gz"

    # Upload to Emergent Object Storage
    result = _put_object(storage_path, gz, "application/gzip")

    rec = {
        "id": file_id,
        "storage_path": result.get("path", storage_path),
        "original_filename": f"jawad-backup-{day}.json.gz",
        "size": result.get("size", len(gz)),
        "raw_size": len(raw),
        "content_type": "application/gzip",
        "download_token": token,
        "token_expires_at": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
        "trigger": trigger,
        "collections": list(snapshot.keys()),
        "created_at": now_iso(),
    }
    await db.backup_files.insert_one(rec)

    # Retain only last 14 backup records + delete their objects (best-effort)
    old = await db.backup_files.find().sort("created_at", -1).skip(14).to_list(500)
    for o in old:
        try:
            await db.backup_files.delete_one({"id": o["id"]})
        except Exception:
            pass

    # Send email (best-effort — do not fail the whole job if email fails).
    # Keep configuration failures in the backup record instead of silently
    # reporting a successful backup with no delivery attempt.
    email_ids = []
    email_error = None
    settings_doc = await db.settings.find_one({"key": "app_settings"}) or {}
    configured_emails = settings_doc.get("backup_emails") or []
    if isinstance(configured_emails, str):
        configured_emails = _re.split(r"[\n,;]+", configured_emails)
    if not configured_emails and settings_doc.get("backup_email"):
        configured_emails = [settings_doc.get("backup_email")]
    to_addrs = list(dict.fromkeys(str(x).strip().lower() for x in configured_emails if str(x).strip()))
    if not to_addrs:
        email_error = "لا يوجد بريد مستلم محفوظ للنسخ الاحتياطي"
    elif not PUBLIC_BASE_URL:
        email_error = "PUBLIC_BASE_URL غير مضبوط؛ تعذر إنشاء رابط تحميل النسخة"
    else:
        link = f"{PUBLIC_BASE_URL}/api/backup/download/{token}"
        subject = f"نسخة احتياطية جديدة — {EMAIL_FROM_NAME} — {day}"
        size_kb = f"{len(gz)/1024:.1f} KB"
        html = (
            '<div dir="rtl" style="font-family:Tahoma,Arial,sans-serif;background:#f6f6fb;padding:24px">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:10px;'
            'box-shadow:0 2px 8px rgba(0,0,0,0.05);overflow:hidden">'
            '<tr><td style="background:#221340;padding:20px 24px;color:#fff">'
            f'<div style="font-size:18px;font-weight:bold">{_html_escape(EMAIL_FROM_NAME)}</div>'
            '<div style="font-size:13px;opacity:.85;margin-top:4px">النسخ الاحتياطي التلقائي</div>'
            '</td></tr>'
            '<tr><td style="padding:24px;color:#221340">'
            f'<p style="font-size:15px;line-height:1.7">تم إنشاء نسخة احتياطية جديدة من قاعدة بيانات {_html_escape(EMAIL_FROM_NAME)} بنجاح بتاريخ <strong>{_html_escape(day)}</strong>.</p>'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="background:#f6f4fb;border-radius:8px;padding:12px;margin:12px 0">'
            f'<tr><td style="padding:6px 10px;font-size:13px">حجم الملف المضغوط: <strong>{_html_escape(size_kb)}</strong></td></tr>'
            f'<tr><td style="padding:6px 10px;font-size:13px">عدد المجموعات: <strong>{len(BACKUP_COLLECTIONS)}</strong></td></tr>'
            f'<tr><td style="padding:6px 10px;font-size:13px">مصدر التشغيل: <strong>{_html_escape(trigger)}</strong></td></tr>'
            '</table>'
            f'<p style="font-size:14px;margin-top:20px">لتحميل الملف اضغط الزر أدناه (صالح لمدة 14 يوماً):</p>'
            f'<p style="margin:20px 0"><a href="{link}" style="background:#452480;color:#fff;text-decoration:none;'
            'padding:12px 24px;border-radius:6px;font-weight:bold;display:inline-block">تحميل النسخة الاحتياطية</a></p>'
            '<p style="font-size:12px;color:#666;margin-top:24px;padding-top:16px;border-top:1px solid #eee">'
            f'أُرسل بواسطة {_html_escape(EMAIL_FROM_NAME)}. لن نطلب منك كلمة المرور أو أي بيانات حساسة عبر البريد.'
            '</p>'
            '</td></tr></table></div>'
        )
        for to_addr in to_addrs:
            try:
                sent_id = await send_email(to=to_addr, subject=subject, html=html)
                if sent_id:
                    email_ids.append(sent_id)
            except HTTPException as e:
                email_error = f"{e.status_code}: {e.detail}"
                logger.error(f"Backup email failed for {to_addr}: {email_error}")
            except Exception as e:
                email_error = str(e)
                logger.error(f"Backup email failed for {to_addr}: {e}")

    await db.backup_files.update_one(
        {"id": file_id},
        {"$set": {"email_sent_to": to_addrs or None, "email_ids": email_ids, "email_error": email_error}},
    )

    return {
        "ok": True,
        "backup_id": file_id,
        "size": len(gz),
        "raw_size": len(raw),
        "email_sent": bool(email_ids),
        "email_error": email_error,
        "email_to": to_addrs or None,
        "download_link": f"{PUBLIC_BASE_URL}/api/backup/download/{token}" if PUBLIC_BASE_URL else None,
    }

def _backup_time_parts(value: Any) -> Optional[tuple[int, int]]:
    """Parse the admin setting without allowing an invalid value to crash the worker."""
    text = str(value or "02:00").strip()
    if not _re.fullmatch(r"[0-9]{2}:[0-9]{2}", text):
        return None
    hour, minute = (int(part) for part in text.split(":", 1))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


async def _claim_internal_backup_slot(slot: str, now: datetime) -> bool:
    """Claim one daily slot atomically so multiple FastAPI workers cannot duplicate it."""
    lock_id = f"daily-backup:{slot}"
    existing = await db.backup_schedule_runs.find_one({"_id": lock_id})
    if not existing:
        try:
            await db.backup_schedule_runs.insert_one({
                "_id": lock_id,
                "slot": slot,
                "state": "running",
                "claimed_at": now,
                "created_at": now,
            })
            return True
        except DuplicateKeyError:
            return False

    state = existing.get("state")
    if state == "done":
        return False

    if state == "running":
        claimed_at = existing.get("claimed_at")
        if isinstance(claimed_at, str):
            try:
                claimed_at = datetime.fromisoformat(claimed_at)
            except Exception:
                claimed_at = None
        if claimed_at and claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        if claimed_at and (now - claimed_at).total_seconds() < BACKUP_SCHEDULER_STALE_SECONDS:
            return False
        result = await db.backup_schedule_runs.update_one(
            {"_id": lock_id, "state": "running", "claimed_at": existing.get("claimed_at")},
            {"$set": {"claimed_at": now, "retry_after": None, "error": None}},
        )
        return result.modified_count == 1

    retry_after = existing.get("retry_after")
    if isinstance(retry_after, str):
        try:
            retry_after = datetime.fromisoformat(retry_after)
        except Exception:
            retry_after = None
    if retry_after and retry_after.tzinfo is None:
        retry_after = retry_after.replace(tzinfo=timezone.utc)
    if retry_after and now < retry_after:
        return False
    result = await db.backup_schedule_runs.update_one(
        {"_id": lock_id, "state": "failed", "retry_after": existing.get("retry_after")},
        {"$set": {"state": "running", "claimed_at": now, "retry_after": None, "error": None}},
    )
    return result.modified_count == 1


async def _run_internal_backup_if_due() -> None:
    settings_doc = await db.settings.find_one({"key": "app_settings"}) or {}
    if not bool(settings_doc.get("backup_auto", False)):
        return

    parts = _backup_time_parts(settings_doc.get("backup_time", "02:00"))
    if not parts:
        logger.warning("Automatic backup skipped: invalid backup_time=%r", settings_doc.get("backup_time"))
        return

    now = datetime.now(BACKUP_TIMEZONE)
    target = now.replace(hour=parts[0], minute=parts[1], second=0, microsecond=0)
    # Run once the configured time has arrived. This also catches a restart after the target time.
    if now < target:
        return

    slot = now.date().isoformat()
    now_utc = datetime.now(timezone.utc)
    if not await _claim_internal_backup_slot(slot, now_utc):
        return

    lock_id = f"daily-backup:{slot}"
    try:
        result = await _run_backup_job(trigger=f"internal:{slot}")
        await db.backup_schedule_runs.update_one(
            {"_id": lock_id},
            {"$set": {
                "state": "done",
                "finished_at": datetime.now(timezone.utc),
                "backup_id": result.get("backup_id"),
                "email_sent": result.get("email_sent", False),
                "email_error": result.get("email_error"),
            }},
        )
        logger.info("Internal daily backup done: %s email_sent=%s", result.get("backup_id"), result.get("email_sent"))
    except Exception as exc:
        retry_after = datetime.now(timezone.utc) + timedelta(minutes=5)
        await db.backup_schedule_runs.update_one(
            {"_id": lock_id},
            {"$set": {"state": "failed", "retry_after": retry_after, "error": str(exc)[:500]}},
        )
        logger.error("Internal daily backup failed: %s", exc)


async def _internal_backup_scheduler() -> None:
    """Poll the configured local time; MongoDB provides the cross-worker lock."""
    while True:
        try:
            await _run_internal_backup_if_due()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Internal backup scheduler error: %s", exc)
        await asyncio.sleep(BACKUP_SCHEDULER_POLL_SECONDS)


@api.post("/backup/run-now")
async def backup_run_now(user=Depends(require_perm("backup"))):
    """Admin-triggered manual cloud backup (upload + email)."""
    res = await _run_backup_job(trigger=f"manual:{user.get('username')}")
    await audit_log(user, "run_backup", "system", res["backup_id"])
    return res

@api.get("/backup/latest")
async def backup_latest(user=Depends(require_perm("backup"))):
    """Return metadata of the most recent cloud backup (no download token)."""
    rec = await db.backup_files.find().sort("created_at", -1).limit(1).to_list(1)
    if not rec:
        return {"exists": False}
    d = clean_doc(rec[0])
    d.pop("download_token", None)
    d["exists"] = True
    return d

class RestoreLatestIn(BaseModel):
    confirm: bool = False

@api.post("/backup/restore-latest")
async def backup_restore_latest(payload: RestoreLatestIn, user=Depends(require_perm("backup"))):
    """Restore the most recent cloud backup. Creates a pre-restore safety snapshot first."""
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="التأكيد مطلوب")
    rec = await db.backup_files.find().sort("created_at", -1).limit(1).to_list(1)
    if not rec:
        raise HTTPException(status_code=404, detail="لا توجد نسخة احتياطية سحابية")
    meta = rec[0]
    try:
        data_gz, _ = _get_object(meta["storage_path"])
        raw = gzip.decompress(data_gz)
        snapshot = json.loads(raw.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"فشل قراءة النسخة: {e}")

    # Safety: snapshot current data before wipe
    safety_id = str(uuid.uuid4())
    safety: Dict[str, Any] = {}
    for c in BACKUP_COLLECTIONS:
        docs = await db[c].find().to_list(100000)
        safety[c] = [clean_doc(d) for d in docs]
    await db.backup_snapshots.insert_one({
        "id": safety_id, "data": safety, "created_at": now_iso(),
        "reason": "pre_restore_latest", "source_backup_id": meta.get("id"),
    })

    # Skip restoring users so the admin session survives; also skip settings key
    protected = {"users"}
    restored: Dict[str, int] = {}
    for c in BACKUP_COLLECTIONS:
        if c in protected: continue
        if c in snapshot and isinstance(snapshot[c], list):
            await db[c].delete_many({})
            if snapshot[c]:
                # strip Mongo _id if any leaked
                docs = [{k: v for k, v in d.items() if k != "_id"} for d in snapshot[c]]
                await db[c].insert_many(docs)
                restored[c] = len(docs)
            else:
                restored[c] = 0
    await audit_log(user, "restore_latest_cloud", "system", meta.get("id", ""))
    return {
        "ok": True,
        "source_backup_id": meta.get("id"),
        "source_created_at": meta.get("created_at"),
        "safety_snapshot_id": safety_id,
        "restored": restored,
        "total_docs": sum(restored.values()),
    }

@api.get("/backup/list")
async def backup_list(user=Depends(require_perm("backup"))):
    docs = await db.backup_files.find().sort("created_at", -1).limit(30).to_list(30)
    out = []
    for d in docs:
        c = clean_doc(d)
        c.pop("download_token", None)
        out.append(c)
    return out

@api.get("/backup/download/{token}")
async def backup_download(token: str):
    """Time-limited public download using an unguessable token embedded in the
    email link (first-party HTTPS magic link). Token is stored server-side."""
    if not token or len(token) < 16:
        raise HTTPException(status_code=404, detail="رابط غير صالح")
    rec = await db.backup_files.find_one({"download_token": token})
    if not rec:
        raise HTTPException(status_code=404, detail="النسخة الاحتياطية غير موجودة")
    exp = rec.get("token_expires_at")
    if exp:
        try:
            if datetime.fromisoformat(exp) < datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail="انتهت صلاحية الرابط")
        except HTTPException:
            raise
        except Exception:
            pass
    data, ct = _get_object(rec["storage_path"])
    fname = rec.get("original_filename") or "backup.json.gz"
    return Response(
        content=data,
        media_type=rec.get("content_type") or ct,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

# --- Cron webhook (Emergent platform crons) ---
def _verify_cron_auth(authorization: Optional[str]) -> None:
    if not WEBHOOK_CRON_SECRET:
        raise HTTPException(status_code=503, detail="Cron secret not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    got = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(got, WEBHOOK_CRON_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")

async def _cron_backup_worker():
    """Runs in the background so the webhook can 2xx immediately."""
    try:
        settings_doc = await db.settings.find_one({"key": "app_settings"}) or {}
        if not bool(settings_doc.get("backup_auto", False)):
            logger.info("Daily backup skipped: backup_auto=False")
            return
        res = await _run_backup_job(trigger="cron:daily")
        logger.info(f"Daily backup done: {res.get('backup_id')} email_sent={res.get('email_sent')}")
    except Exception as e:
        logger.error(f"Daily backup worker error: {e}")

@api.post("/cron/daily-backup")
async def cron_daily_backup(
    background_tasks: BackgroundTasks,
    request: Request,
    authorization: Optional[str] = Header(None),
    x_webhook_id: Optional[str] = Header(None),
):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _verify_cron_auth(authorization)
    run_id = x_webhook_id or ""
    if run_id:
        try:
            # Idempotency: skip if we've already handled this run id
            existing = await db.cron_runs.find_one({"run_id": run_id})
            if existing:
                return {"ok": True, "duplicate": True}
            await db.cron_runs.insert_one({"run_id": run_id, "at": now_iso(), "name": "daily-backup"})
        except Exception:
            pass
    background_tasks.add_task(_cron_backup_worker)
    return {"ok": True, "queued": True}


# ================= CUSTOMER PASSWORD REVEAL =================
@api.post("/customers/{cid}/unbind-device")
async def unbind_customer_device(cid: str, user=Depends(require_perm("customers"))):
    """Clear the customer's bound device so the next successful login (with the
    new/reset password) binds the new phone automatically."""
    doc = await db.customers.find_one({"id": cid})
    if not doc: raise HTTPException(status_code=404, detail="غير موجود")
    old_device = doc.get("bound_device")
    await db.customers.update_one(
        {"id": cid},
        {"$set": {"bound_device": None, "bound_device_at": None},
         "$push": {"device_history": {"unbound_at": now_iso(), "unbound_by": user.get("username"), "was": old_device}}},
    )
    await audit_log(user, "unbind_customer_device", "customer", cid, {"name": doc.get("name", ""), "phone": doc.get("phone", "")}, None)
    # Prepare WhatsApp notification the admin can send to the customer
    from urllib.parse import quote
    phone_digits = "".join(ch for ch in (doc.get("phone") or "") if ch.isdigit()).lstrip("0")
    wa_phone = "967" + phone_digits if (phone_digits and not phone_digits.startswith("967")) else phone_digits
    body = await _render_message_template("unbind_account", {
        "name": doc.get("name", ""), "phone": doc.get("phone", ""), "company": "شبكة جواد نت اللاسلكية",
    })
    wa_url = f"https://wa.me/{wa_phone}?text={quote(body)}" if wa_phone and await _message_channel_enabled("unbind_account", "whatsapp") and body else ""
    return {"ok": True, "whatsapp_url": wa_url}


@api.get("/customers/{cid}/password")
async def get_customer_password(cid: str, user=Depends(require_perm("customers"))):
    raise HTTPException(
        status_code=410,
        detail="عرض كلمة المرور غير متاح لأسباب أمنية. استخدم تغيير كلمة المرور وإرسالها للعميل عبر المسار المعتمد.",
    )


# ================= SEARCH =================
@api.get("/search")
async def global_search(q: str, user=Depends(get_current_user)):
    result = {}
    result["sales"] = [clean_doc(s) for s in await db.sales.find({"number": {"$regex": q, "$options": "i"}}).limit(10).to_list(10)]
    result["purchases"] = [clean_doc(s) for s in await db.purchases.find({"number": {"$regex": q, "$options": "i"}}).limit(10).to_list(10)]
    result["receipts"] = [clean_doc(s) for s in await db.receipts.find({"number": {"$regex": q, "$options": "i"}}).limit(10).to_list(10)]
    result["customers"] = [clean_doc(c) for c in await db.customers.find({"$or": [{"name": {"$regex": q, "$options": "i"}}, {"phone": {"$regex": q, "$options": "i"}}]}).limit(10).to_list(10)]
    result["cards"] = [clean_doc(c) for c in await db.cards.find({"number": {"$regex": q, "$options": "i"}}).limit(10).to_list(10)]
    result["suppliers"] = [clean_doc(c) for c in await db.suppliers.find({"$or": [{"name": {"$regex": q, "$options": "i"}}, {"phone": {"$regex": q, "$options": "i"}}]}).limit(10).to_list(10)]
    result["transfers"] = [clean_doc(t) for t in await db.transfers.find({"$or": [
        {"number": {"$regex": q, "$options": "i"}},
        {"reference": {"$regex": q, "$options": "i"}},
    ]}).limit(10).to_list(10)]
    result["free_cards"] = [clean_doc(f) for f in await db.free_card_sends.find({"$or": [
        {"number": {"$regex": q, "$options": "i"}},
        {"card_number": {"$regex": q, "$options": "i"}},
        {"recipient_phone": {"$regex": q, "$options": "i"}},
        {"recipient_name": {"$regex": q, "$options": "i"}},
    ]}).limit(10).to_list(10)]
    return result


# ================= SETTINGS =================
@api.get("/settings")
async def get_settings(user=Depends(get_current_user)):
    doc = await db.settings.find_one({"key": "app_settings"}) or {}
    legacy_email = doc.get("backup_email", "")
    backup_emails = doc.get("backup_emails") or ([legacy_email] if legacy_email else [])
    notification_settings = {**DEFAULT_NOTIFICATION_SETTINGS, **(doc.get("notification_settings") or {})}
    messaging_settings = {**DEFAULT_MESSAGING_SETTINGS, **(doc.get("messaging_settings") or {})}
    event_settings = {}
    for key, default in DEFAULT_MESSAGE_EVENT_SETTINGS.items():
        if not isinstance(default, dict) or "channels" not in default:
            default = {"enabled": True, "channels": ["in_app"]}
        incoming = (doc.get("message_event_settings") or {}).get(key) or {}
        channels = incoming.get("channels", default["channels"])
        if not isinstance(channels, list):
            channels = list(default["channels"])
        event_settings[key] = {
            "enabled": bool(incoming.get("enabled", default["enabled"])),
            "channels": [c for c in channels if c in ("in_app", "whatsapp", "sms")],
        }
    template_docs = await db.message_templates.find({}, {"_id": 0}).to_list(100)
    custom_templates = {d.get("key"): d for d in template_docs}
    message_templates = [
        {
            "key": key,
            **default,
            "text": (custom_templates.get(key) or {}).get("text") or default["text"],
            "default_text": default["text"],
            "customized": bool((custom_templates.get(key) or {}).get("text")),
        }
        for key, default in MESSAGE_TEMPLATE_DEFAULTS.items()
    ]
    return {
        "company_name": COMPANY_NAME,
        "company_phone": COMPANY_PHONE,
        "currency": doc.get("currency", "ريال"),
        "logo_url": doc.get("logo_url", ""),
        "low_stock_default": doc.get("low_stock_default", 20),
        "backup_email": legacy_email,
        "backup_emails": backup_emails,
        "backup_time": doc.get("backup_time", "02:00"),
        "backup_auto": bool(doc.get("backup_auto", False)),
        "install_allowed_emails": doc.get("install_allowed_emails", ["mofeedaldhlaa@gmail.com"]),
        "auto_message_prefix": doc.get("auto_message_prefix", ""),
        "auto_message_suffix": doc.get("auto_message_suffix", ""),
        "notification_settings": notification_settings,
        "messaging_settings": messaging_settings,
        "message_event_settings": event_settings,
        "message_templates": message_templates,
    }

@api.post("/settings")
async def update_settings(data: SettingsIn, user=Depends(require_perm("settings"))):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if "notification_settings" in update:
        incoming = update["notification_settings"] or {}
        update["notification_settings"] = {
            key: bool(incoming.get(key, default))
            for key, default in DEFAULT_NOTIFICATION_SETTINGS.items()
        }
    if "messaging_settings" in update:
        incoming = update["messaging_settings"] or {}
        default_channel = incoming.get("default_channel", DEFAULT_MESSAGING_SETTINGS["default_channel"])
        if default_channel not in ("whatsapp", "sms"):
            raise HTTPException(status_code=400, detail="قناة الإرسال الافتراضية غير صحيحة")
        country_code = str(incoming.get("country_code", DEFAULT_MESSAGING_SETTINGS["country_code"])).strip()
        if not country_code.startswith("+") or not country_code[1:].isdigit():
            raise HTTPException(status_code=400, detail="رمز الدولة غير صحيح")
        update["messaging_settings"] = {
            "whatsapp_enabled": bool(incoming.get("whatsapp_enabled", True)),
            "sms_enabled": bool(incoming.get("sms_enabled", True)),
            "default_channel": default_channel,
            "country_code": country_code[:8],
            "append_company_name": bool(incoming.get("append_company_name", True)),
        }
    template_updates = update.pop("message_templates", None)
    if template_updates is not None:
        if not isinstance(template_updates, dict):
            raise HTTPException(status_code=400, detail="إعدادات القوالب غير صحيحة")
        unknown = [key for key in template_updates if key not in MESSAGE_TEMPLATE_DEFAULTS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"قالب غير معروف: {unknown[0]}")
        for key, value in template_updates.items():
            text = str(value or "").strip()
            if len(text) > 5000:
                raise HTTPException(status_code=400, detail="نص القالب طويل جداً")
            if text:
                await db.message_templates.update_one(
                    {"key": key},
                    {"$set": {"key": key, "text": text, "updated_at": now_iso(), "updated_by": user.get("username")}},
                    upsert=True,
                )
            else:
                await db.message_templates.delete_one({"key": key})
    if "message_event_settings" in update:
        incoming = update["message_event_settings"] or {}
        if not isinstance(incoming, dict):
            raise HTTPException(status_code=400, detail="إعدادات أحداث الرسائل غير صحيحة")
        normalized_events = {}
        for key, default in DEFAULT_MESSAGE_EVENT_SETTINGS.items():
            value = incoming.get(key) or {}
            channels = value.get("channels", default["channels"]) if isinstance(value, dict) else default["channels"]
            if not isinstance(channels, list):
                channels = list(default["channels"])
            channels = [str(channel) for channel in channels if str(channel) in ("in_app", "whatsapp", "sms")]
            normalized_events[key] = {
                "enabled": bool(value.get("enabled", default["enabled"])) if isinstance(value, dict) else bool(default["enabled"]),
                "channels": channels,
            }
        update["message_event_settings"] = normalized_events
    # Validate backup_email format at the API boundary
    if "backup_email" in update:
        v = (update["backup_email"] or "").strip()
        if v:
            import re
            if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", v):
                raise HTTPException(status_code=400, detail="البريد الإلكتروني غير صحيح")
        update["backup_email"] = v
    if "backup_emails" in update:
        emails = [str(e).strip().lower() for e in (update["backup_emails"] or []) if str(e).strip()]
        rx = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
        bad = [e for e in emails if not rx.match(e)]
        if bad:
            raise HTTPException(status_code=400, detail=f"إيميل غير صحيح: {bad[0]}")
        update["backup_emails"] = list(dict.fromkeys(emails))
    if "backup_time" in update and _backup_time_parts(update["backup_time"]) is None:
        raise HTTPException(status_code=400, detail="وقت النسخ الاحتياطي غير صحيح. استخدم الصيغة HH:MM")
    if "install_allowed_emails" in update:
        emails = [str(e).strip().lower() for e in (update["install_allowed_emails"] or []) if str(e).strip()]
        import re
        rx = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
        bad = [e for e in emails if not rx.match(e)]
        if bad:
            raise HTTPException(status_code=400, detail=f"إيميل غير صحيح: {bad[0]}")
        update["install_allowed_emails"] = emails
    await db.settings.update_one({"key": "app_settings"}, {"$set": update}, upsert=True)
    return await get_settings(user)


# ================= FILES (Object storage) =================
MAX_UPLOAD_MB = 25

@api.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    user=Depends(get_current_user),
):
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"حجم الملف أكبر من {MAX_UPLOAD_MB} ميجابايت")
    name = (file.filename or "file").strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "bin"
    path = f"{APP_NAME}/uploads/{user.get('id') or user.get('username')}/{uuid.uuid4()}.{ext}"
    ct = file.content_type or "application/octet-stream"
    result = _put_object(path, data, ct)
    doc = {
        "id": str(uuid.uuid4()),
        "storage_path": result.get("path", path),
        "original_filename": name,
        "content_type": ct,
        "size": result.get("size", len(data)),
        "entity_type": entity_type or "general",
        "entity_id": entity_id,
        "uploaded_by": user.get("username"),
        "is_deleted": False,
        "created_at": now_iso(),
    }
    await db.files.insert_one(doc)
    return clean_doc(doc)

@api.get("/files")
async def list_files(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user=Depends(get_current_user),
):
    q: Dict[str, Any] = {"is_deleted": False}
    if entity_type: q["entity_type"] = entity_type
    if entity_id: q["entity_id"] = entity_id
    docs = await db.files.find(q).sort("created_at", -1).limit(500).to_list(500)
    return [clean_doc(d) for d in docs]

@api.get("/files/{fid}/download")
async def download_file(fid: str, authorization: Optional[str] = Header(None), auth: Optional[str] = Query(None)):
    # Accept auth via header OR ?auth=<jwt> so <img src> / <a href> can work without JS wrappers.
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
    elif auth:
        token = auth
    if not token: raise HTTPException(status_code=401, detail="مطلوب مصادقة")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        u = await db.users.find_one({"id": payload.get("sub")})
        if not u or u.get("status") == "disabled": raise Exception()
    except Exception:
        raise HTTPException(status_code=401, detail="جلسة غير صالحة")
    rec = await db.files.find_one({"id": fid, "is_deleted": False})
    if not rec: raise HTTPException(status_code=404, detail="الملف غير موجود")
    data, ct = _get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type") or ct,
                    headers={"Content-Disposition": f'inline; filename="{rec.get("original_filename","file")}"'})

@api.delete("/files/{fid}")
async def delete_file(fid: str, user=Depends(get_current_user)):
    rec = await db.files.find_one({"id": fid, "is_deleted": False})
    if not rec: raise HTTPException(status_code=404, detail="الملف غير موجود")
    await db.files.update_one({"id": fid}, {"$set": {"is_deleted": True, "deleted_at": now_iso(), "deleted_by": user.get("username")}})
    return {"ok": True}


# ================= STARTUP =================
@app.on_event("startup")
async def startup():
    # Object storage
    try:
        if init_storage():
            logger.info("Storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
    # Indexes
    await db.users.create_index("username", unique=True)
    await db.customers.create_index("phone")
    try:
        assigned_alternative_numbers = await _ensure_all_alternative_numbers()
        logger.info("Alternative account numbers ready for %s customers", assigned_alternative_numbers)
    except Exception as exc:
        # Keep the API bootable during a concurrent worker race; the next worker
        # restart retries the idempotent backfill and never changes assigned numbers.
        logger.error("Alternative account-number migration failed: %s", exc)
    await db.cards.create_index("number", unique=True)
    await db.card_pdf_previews.create_index("id", unique=True)
    await db.card_pdf_previews.create_index("sha256")
    await db.sales.create_index("number", unique=True)
    async def ensure_unique_idempotency_index(collection):
        indexes = await collection.index_information()
        current = indexes.get("idempotency_key_1")
        if current and not current.get("unique"):
            await collection.drop_index("idempotency_key_1")
        await collection.create_index(
            "idempotency_key",
            unique=True,
            partialFilterExpression={"idempotency_key": {"$gt": ""}},
        )

    await ensure_unique_idempotency_index(db.sales)
    await db.purchases.create_index("number", unique=True)
    await ensure_unique_idempotency_index(db.purchases)
    await db.transfers.create_index("number")
    await ensure_unique_idempotency_index(db.transfers)
    await db.stock_ops.create_index("category_id")
    await db.stock_ops.create_index("created_at")
    await db.stock_ops.create_index("number", unique=True, partialFilterExpression={"number": {"$type": "string", "$gt": ""}}, name="stock_operation_number_unique")
    await db.currencies.create_index("symbol", unique=True)
    await db.payment_requests.create_index("party_id")
    await ensure_unique_idempotency_index(db.payment_requests)
    await ensure_unique_idempotency_index(db.payment_verifications)
    try:
        await db.direct_card_purchases.create_index(
            "payment_reference_normalized",
            unique=True,
            partialFilterExpression={"payment_reference_normalized": {"$type": "string", "$gt": ""}},
            name="direct_card_payment_reference_unique",
        )
    except Exception as exc:
        # Keep an existing deployment bootable if legacy duplicate references
        # need an administrator's audit before the unique guard can be enabled.
        logger.error("direct-card reference unique index unavailable: %s", exc)
    await db.payment_verifications.create_index(
        "client_transaction_id",
        unique=True,
        partialFilterExpression={"client_transaction_id": {"$type": "string", "$gt": ""}},
        name="payment_verification_transaction_unique",
    )
    await db.cashboxes.create_index(
        "bank_account_id",
        unique=True,
        partialFilterExpression={"bank_account_id": {"$type": "string", "$gt": ""}},
        name="cashbox_bank_account_unique",
    )
    try:
        migrated_senders = await _migrate_legacy_gateway_sender_ids_to_banks()
        if migrated_senders:
            logger.info("Migrated Sender IDs from payment_gateway settings to %s bank accounts", migrated_senders)
    except Exception as exc:
        logger.error("Gateway Sender migration failed: %s", exc)
    try:
        await _ensure_all_bank_cashboxes()
    except Exception as exc:
        # A legacy deployment must still start if a pre-existing duplicate is
        # found; the unique index remains the final guard for new data.
        logger.error("Linked bank cashbox backfill failed: %s", exc)
    await db.payment_verifications.create_index("customer_id")
    await db.payment_verifications.create_index("status")
    await db.payment_gateway_messages.create_index(
        "normalized_message_fingerprint",
        unique=True,
        name="payment_gateway_message_fingerprint_unique",
    )
    await db.payment_gateway_messages.create_index(
        "transaction_id",
        unique=True,
        partialFilterExpression={"transaction_id": {"$type": "string", "$gt": ""}},
        name="payment_gateway_transaction_unique",
    )
    await db.payment_gateway_nonces.create_index("nonce", unique=True, name="payment_gateway_nonce_unique")
    await db.payment_gateway_nonces.create_index("expires_at", expireAfterSeconds=0, name="payment_gateway_nonce_ttl")
    await db.receipts.create_index("number", unique=True)
    await db.receipts.create_index(
        "payment_verification_id",
        unique=True,
        partialFilterExpression={"payment_verification_id": {"$type": "string", "$gt": ""}},
        name="receipt_payment_verification_unique",
    )
    await ensure_unique_idempotency_index(db.receipts)
    await ensure_unique_idempotency_index(db.expenses)
    # The HTTP middleware and route-level guard both use this collection. Older
    # versions omitted idempotency_key from HTTP claims, which collided with
    # Mongo's unique (scope, idempotency_key) index where null was treated as a
    # single value; every later online mutation then returned 409.
    claim_indexes = await db.operation_claims.index_information()
    for index_name, index_info in claim_indexes.items():
        if index_name == "_id_":
            continue
        if index_info.get("key") == [("scope", 1), ("idempotency_key", 1)]:
            try:
                await db.operation_claims.drop_index(index_name)
            except Exception as exc:
                # MongoDB can report a stale index name during concurrent startup; continue safely.
                logger.warning("تعذر حذف فهرس قديم %s أثناء التهيئة: %s", index_name, exc)
    await db.operation_claims.create_index(
        [("scope", 1), ("idempotency_key", 1)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string", "$gt": ""}},
        name="operation_claim_scope_key_unique",
    )
    await db.notification_reads.create_index([("user_id", 1), ("notification_id", 1)], unique=True)
    await db.push_subscriptions.create_index("endpoint", unique=True)

    # Never create or mutate privileged accounts as a side effect of deployment.
    # Existing users and permissions are preserved exactly as stored.

    _existing_admin_any = await db.users.find_one({"role": "admin"})
    if not _existing_admin_any:
        logger.info("No admin user present; the FIRST user created via /api/users will become the system admin.")
    # Seed default categories if empty
    cats_count = await db.card_categories.count_documents({})
    if cats_count == 0:
        defaults = [
            {"name": "200 ريال", "value": 200, "sale_price": 200, "purchase_price": 180, "validity_days": 30, "data_size": "5GB"},
            {"name": "300 ريال", "value": 300, "sale_price": 300, "purchase_price": 270, "validity_days": 30, "data_size": "10GB"},
            {"name": "500 ريال", "value": 500, "sale_price": 500, "purchase_price": 450, "validity_days": 30, "data_size": "20GB"},
            {"name": "1000 ريال", "value": 1000, "sale_price": 1000, "purchase_price": 900, "validity_days": 30, "data_size": "50GB"},
            {"name": "3000 ريال", "value": 3000, "sale_price": 3000, "purchase_price": 2700, "validity_days": 90, "data_size": "200GB"},
            {"name": "5000 ريال", "value": 5000, "sale_price": 5000, "purchase_price": 4500, "validity_days": 180, "data_size": "unlimited"},
        ]
        for d in defaults:
            await db.card_categories.insert_one({
                **d, "id": str(uuid.uuid4()), "status": "active",
                "notes": "", "low_stock_threshold": 20, "created_at": now_iso(),
            })
    balance_category = await db.card_categories.find_one({"$or": [{"kind": "balance"}, {"name": BALANCE_CATEGORY_NAME}]})
    if balance_category:
        if balance_category.get("kind") != "balance":
            await db.card_categories.update_one({"id": balance_category["id"]}, {"$set": {"kind": "balance", "show_in_public": False}})
    else:
        await db.card_categories.insert_one({
            "id": str(uuid.uuid4()), "name": BALANCE_CATEGORY_NAME, "kind": "balance", "value": 0,
            "sale_price": 0, "sale_price_customer": 0, "sale_price_pos": 0, "purchase_price": 0,
            "validity_days": 0, "data_size": "مالي", "status": "active", "show_in_public": False,
            "notes": "فئة مالية مخصصة لتحويل الرصيد", "low_stock_threshold": 0,
            "low_stock_numbered": 0, "low_stock_quantity": 0, "created_at": now_iso(),
        })

    # Run one due-check synchronously during startup so a service restart cannot
    # miss the configured daily slot before the polling task gets its first tick.
    # MongoDB slot claiming remains the single-writer guard across workers.
    try:
        await _run_internal_backup_if_due()
    except Exception as exc:
        logger.error("Internal backup startup check failed: %s", exc)

    global _backup_scheduler_task
    if _backup_scheduler_task is None or _backup_scheduler_task.done():
        _backup_scheduler_task = asyncio.create_task(_internal_backup_scheduler(), name="internal-daily-backup")
        logger.info("Internal daily backup scheduler started (timezone=Asia/Aden, poll=%ss)", BACKUP_SCHEDULER_POLL_SECONDS)
    global _stock_alert_task
    if _stock_alert_task is None or _stock_alert_task.done():
        _stock_alert_task = asyncio.create_task(_stock_alert_watch_loop(), name="stock-alert-watcher")
        logger.info("Stock alert watcher started (poll=%ss)", STOCK_ALERT_WATCH_SECONDS)

@app.on_event("shutdown")
async def shutdown():
    global _backup_scheduler_task
    if _backup_scheduler_task and not _backup_scheduler_task.done():
        _backup_scheduler_task.cancel()
        try:
            await _backup_scheduler_task
        except asyncio.CancelledError:
            pass
        _backup_scheduler_task = None
    global _stock_alert_task
    if _stock_alert_task and not _stock_alert_task.done():
        _stock_alert_task.cancel()
        try:
            await _stock_alert_task
        except asyncio.CancelledError:
            pass
        _stock_alert_task = None
    client.close()

# === إشعارات فورية (FCM) ===
async def _send_fcm(
    title: str,
    message: str,
    ntype: str = "info",
    target_user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    customer_only: bool = False,
):
    """يرسل إشعاراً فورياً عبر Firebase Cloud Messaging للأجهزة المسجَّلة."""
    try:
        import firebase_push
    except Exception as exc:  # pragma: no cover
        logger.warning("firebase_push غير متاح: %s", exc)
        return
    if not firebase_push.is_configured():
        return
    try:
        query: Dict[str, Any] = {"enabled": {"$ne": False}}
        if target_user_id:
            if customer_only:
                # خاص بعميل: أجهزته فقط، بلا توسّع إلى أجهزة الإدارة
                query["$or"] = [
                    {"customer_id": target_user_id},
                    {"user_id": target_user_id},
                ]
            else:
                query["$or"] = [
                    {"user_id": target_user_id},
                    {"customer_id": target_user_id},
                    {"audience": "all"},
                ]
        tokens: List[str] = []
        async for row in db.device_tokens.find(query, {"token": 1, "_id": 0}).limit(500):
            value = str(row.get("token") or "").strip()
            if value:
                tokens.append(value)
        if not tokens:
            return
        payload = dict(details or {})
        payload["type"] = str(ntype or "info")
        result = await asyncio.to_thread(firebase_push.send, tokens, title, message, payload)
        dead = result.get("dead") or []
        if dead:
            await db.device_tokens.delete_many({"token": {"$in": dead}})
        if result.get("errors"):
            logger.warning("FCM errors: %s", result["errors"][:3])
    except Exception as exc:  # pragma: no cover
        logger.warning("فشل إرسال إشعار FCM: %s", exc)


async def _notify_push(notif_id: str, title: str, message: str, ntype: str = "info",
                       details: Optional[Dict[str, Any]] = None,
                       user_id: Optional[str] = None, customer_id: Optional[str] = None):
    """يدفع إشعاراً مُدرجاً حديثاً إلى الأجهزة (FCM) وبوابة العميل (Web Push).
    يُستخدم مع الإشعارات التي تُدرج مباشرة في قاعدة البيانات."""
    try:
        settings, _ = await _app_channel_settings()
    except Exception:
        settings = {}
    if not settings.get("enabled", True):
        return
    payload = dict(details or {})
    payload["notification_id"] = notif_id
    target = user_id or customer_id
    customer_only = bool(customer_id) and not user_id
    if settings.get("web_push_enabled", True):
        asyncio.create_task(_send_web_push(title, message, ntype, target))
    if settings.get("fcm_enabled", True):
        asyncio.create_task(_send_fcm(title, message, ntype, target, payload, customer_only))

class DeviceTokenIn(BaseModel):
    token: str
    device_id: Optional[str] = None
    user_id: Optional[str] = None
    customer_id: Optional[str] = None
    platform: Optional[str] = "android"
    app_version: Optional[str] = None
    audience: Optional[str] = None


@api.post("/devices/fcm-token")
async def register_device_token(data: DeviceTokenIn):
    """تسجيل أو تحديث توكن إشعارات الجهاز (يُستدعى من تطبيق الأندرويد)."""
    token_value = (data.token or "").strip()
    if not token_value:
        raise HTTPException(status_code=400, detail="التوكن مطلوب")
    stamp = now_iso()
    update: Dict[str, Any] = {
        "token": token_value,
        "platform": data.platform or "android",
        "app_version": data.app_version,
        "user_id": (data.user_id or "").strip() or None,
        "customer_id": (data.customer_id or "").strip() or None,
        "enabled": True,
        "updated_at": stamp,
    }
    if not update["user_id"] and not update["customer_id"]:
        update["audience"] = (data.audience or "all").strip() or "all"
    if data.device_id:
        update["device_id"] = data.device_id
    await db.device_tokens.update_one(
        {"token": token_value},
        {"$set": update, "$setOnInsert": {"created_at": stamp}},
        upsert=True,
    )
    return {"ok": True}


@api.delete("/devices/fcm-token")
async def unregister_device_token(token: str, user=Depends(get_current_user)):
    """حذف توكن جهاز (عند تسجيل الخروج من التطبيق)."""
    await db.device_tokens.delete_many({"token": (token or "").strip()})
    return {"ok": True}



app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_methods=["*"],
    allow_headers=["*"],
)

# deploy marker 1789146047.5735972
