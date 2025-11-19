"""
Database Schemas for StudioLux

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase of the class name.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    hashed_password: str = Field(..., description="Password hash")
    is_admin: bool = Field(False, description="Admin access flag")

class Sessiontoken(BaseModel):
    user_id: str
    token: str
    expires_at: datetime

class Selfieroom(BaseModel):
    title: str
    slug: str
    description: str
    price_per_session: float
    images: List[str] = []
    active: bool = True

class Booking(BaseModel):
    user_id: str
    room_id: str
    start_time: datetime
    end_time: datetime
    status: Literal["pending", "confirmed", "cancelled"] = "pending"
    total_amount: float

class Equipment(BaseModel):
    name: str
    slug: str
    description: str
    price_per_day: float
    stock: int = 1
    images: List[str] = []
    active: bool = True

class Rental(BaseModel):
    user_id: str
    equipment_id: str
    start_date: datetime
    end_date: datetime
    days: int
    status: Literal["pending", "confirmed", "cancelled"] = "pending"
    total_amount: float

class Payment(BaseModel):
    user_id: str
    amount: float
    currency: str = "USD"
    status: Literal["pending", "paid", "failed"] = "pending"
    provider: str = "mock"
    reference: Optional[str] = None
    items: List[dict] = []
    related_type: Literal["booking", "rental"]
    related_id: str
