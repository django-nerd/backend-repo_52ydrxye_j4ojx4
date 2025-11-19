import os
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User, Selfieroom, Equipment, Booking, Rental, Payment, Sessiontoken

app = FastAPI(title="StudioLux API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------
# Helpers
# ------------------------

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


def now_utc() -> datetime:
    return datetime.utcnow()


class AuthUser(BaseModel):
    id: str
    name: str
    email: str
    is_admin: bool = False


def get_current_user(authorization: Optional[str] = Header(default=None)) -> Optional[AuthUser]:
    if not authorization:
        return None
    # Expect Bearer token
    parts = authorization.split()
    token = parts[-1]
    token_doc = db["sessiontoken"].find_one({"token": token, "expires_at": {"$gt": now_utc()}})
    if not token_doc:
        return None
    user = db["user"].find_one({"_id": token_doc["user_id"]}) if isinstance(token_doc.get("user_id"), ObjectId) else db["user"].find_one({"_id": oid(token_doc["user_id"])})
    if not user:
        return None
    return AuthUser(id=str(user["_id"]), name=user.get("name"), email=user.get("email"), is_admin=user.get("is_admin", False))


def require_auth(user: Optional[AuthUser]) -> AuthUser:
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def require_admin(user: Optional[AuthUser]) -> AuthUser:
    u = require_auth(user)
    if not u.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return u


# ------------------------
# Models for requests
# ------------------------
class SignupRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateRoomRequest(BaseModel):
    title: str
    slug: str
    description: str
    price_per_session: float
    images: List[str] = []
    active: bool = True


class CreateEquipmentRequest(BaseModel):
    name: str
    slug: str
    description: str
    price_per_day: float
    stock: int = 1
    images: List[str] = []
    active: bool = True


class CreateBookingRequest(BaseModel):
    room_id: str
    start_time: datetime
    end_time: datetime
    total_amount: float


class CreateRentalRequest(BaseModel):
    equipment_id: str
    start_date: datetime
    end_date: datetime
    days: int
    total_amount: float


class CheckoutItem(BaseModel):
    label: str
    quantity: int
    amount: float


class CheckoutRequest(BaseModel):
    items: List[CheckoutItem]
    related_type: str
    related_id: str
    amount: float
    currency: str = "USD"


# ------------------------
# Root & health
# ------------------------
@app.get("/")
def root():
    return {"app": "StudioLux API", "status": "ok"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected & Working"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
            except Exception:
                pass
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# ------------------------
# Auth
# ------------------------
@app.post("/api/auth/signup")
def signup(payload: SignupRequest):
    if db["user"].find_one({"email": payload.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(name=payload.name, email=payload.email, hashed_password=payload.password, is_admin=False)
    user_id = create_document("user", user)
    return {"id": user_id}


@app.post("/api/auth/login")
def login(payload: LoginRequest):
    user = db["user"].find_one({"email": payload.email})
    if not user or user.get("hashed_password") != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # issue token
    token_value = os.urandom(16).hex()
    expires_at = now_utc() + timedelta(days=7)
    token_doc = Sessiontoken(user_id=str(user["_id"]), token=token_value, expires_at=expires_at)
    create_document("sessiontoken", token_doc)
    return {"token": token_value, "user": {"id": str(user["_id"]), "name": user.get("name"), "email": user.get("email"), "is_admin": user.get("is_admin", False)}}


@app.get("/api/auth/me")
def me(user: Optional[AuthUser] = Depends(get_current_user)):
    u = require_auth(user)
    return u


# ------------------------
# Rooms
# ------------------------
@app.get("/api/rooms")
def list_rooms(active: Optional[bool] = None):
    q = {}
    if active is not None:
        q["active"] = active
    rooms = get_documents("selfieroom", q)
    for r in rooms:
        r["id"] = str(r.pop("_id"))
    return rooms


@app.post("/api/rooms")
def create_room(payload: CreateRoomRequest, user: Optional[AuthUser] = Depends(get_current_user)):
    require_admin(user)
    room = Selfieroom(**payload.model_dump())
    room_id = create_document("selfieroom", room)
    return {"id": room_id}


@app.get("/api/rooms/{slug}")
def get_room(slug: str):
    r = db["selfieroom"].find_one({"slug": slug})
    if not r:
        raise HTTPException(status_code=404, detail="Room not found")
    r["id"] = str(r.pop("_id"))
    return r


@app.get("/api/rooms/{room_id}/availability")
def room_availability(room_id: str, date: str = Query(..., description="YYYY-MM-DD")):
    # Return list of unavailable time ranges for the date
    try:
        day = datetime.strptime(date, "%Y-%m-%d")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")
    next_day = day + timedelta(days=1)
    bookings = list(db["booking"].find({
        "room_id": room_id,
        "start_time": {"$lt": next_day},
        "end_time": {"$gt": day}
    }))
    blocks = [{
        "start_time": b.get("start_time").isoformat(),
        "end_time": b.get("end_time").isoformat(),
        "status": b.get("status", "confirmed")
    } for b in bookings]
    return {"date": date, "unavailable": blocks}


# ------------------------
# Bookings
# ------------------------
@app.post("/api/bookings")
def create_booking(payload: CreateBookingRequest, user: Optional[AuthUser] = Depends(get_current_user)):
    u = require_auth(user)
    # check conflicts
    overlap = db["booking"].find_one({
        "room_id": payload.room_id,
        "$or": [
            {"start_time": {"$lt": payload.end_time}, "end_time": {"$gt": payload.start_time}}
        ]
    })
    if overlap:
        raise HTTPException(status_code=400, detail="Time slot not available")
    booking = Booking(user_id=u.id, room_id=payload.room_id, start_time=payload.start_time, end_time=payload.end_time, total_amount=payload.total_amount, status="confirmed")
    booking_id = create_document("booking", booking)
    return {"id": booking_id, "status": "confirmed"}


@app.get("/api/bookings")
def list_bookings(user: Optional[AuthUser] = Depends(get_current_user)):
    u = require_auth(user)
    q = {} if u.is_admin else {"user_id": u.id}
    items = list(db["booking"].find(q).sort("created_at", -1))
    for i in items:
        i["id"] = str(i.pop("_id"))
    return items


# ------------------------
# Equipment & Rentals
# ------------------------
@app.get("/api/equipment")
def list_equipment(active: Optional[bool] = None):
    q = {}
    if active is not None:
        q["active"] = active
    items = get_documents("equipment", q)
    for i in items:
        i["id"] = str(i.pop("_id"))
    return items


@app.post("/api/equipment")
def create_equipment(payload: CreateEquipmentRequest, user: Optional[AuthUser] = Depends(get_current_user)):
    require_admin(user)
    eq = Equipment(**payload.model_dump())
    eq_id = create_document("equipment", eq)
    return {"id": eq_id}


@app.post("/api/rentals")
def create_rental(payload: CreateRentalRequest, user: Optional[AuthUser] = Depends(get_current_user)):
    u = require_auth(user)
    rental = Rental(user_id=u.id, equipment_id=payload.equipment_id, start_date=payload.start_date, end_date=payload.end_date, days=payload.days, total_amount=payload.total_amount, status="confirmed")
    rental_id = create_document("rental", rental)
    return {"id": rental_id, "status": "confirmed"}


# ------------------------
# Payments (Mock)
# ------------------------
@app.post("/api/checkout")
def checkout(payload: CheckoutRequest, user: Optional[AuthUser] = Depends(get_current_user)):
    u = require_auth(user)
    payment = Payment(user_id=u.id, amount=payload.amount, status="paid", provider="mock", items=[i.model_dump() for i in payload.items], related_type=payload.related_type, related_id=payload.related_id, currency=payload.currency)
    payment_id = create_document("payment", payment)
    return {"status": "paid", "payment_id": payment_id}


# ------------------------
# Admin Overview
# ------------------------
@app.get("/api/admin/overview")
def admin_overview(user: Optional[AuthUser] = Depends(get_current_user)):
    require_admin(user)
    stats = {
        "users": db["user"].count_documents({}),
        "rooms": db["selfieroom"].count_documents({}),
        "equipment": db["equipment"].count_documents({}),
        "bookings": db["booking"].count_documents({}),
        "rentals": db["rental"].count_documents({}),
        "payments": db["payment"].count_documents({}),
    }
    recent = {
        "bookings": [
            {"id": str(x["_id"]), "room_id": x.get("room_id"), "start_time": x.get("start_time"), "total_amount": x.get("total_amount")}
            for x in db["booking"].find().sort("created_at", -1).limit(5)
        ],
        "payments": [
            {"id": str(x["_id"]), "amount": x.get("amount"), "status": x.get("status")}
            for x in db["payment"].find().sort("created_at", -1).limit(5)
        ]
    }
    return {"stats": stats, "recent": recent}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
