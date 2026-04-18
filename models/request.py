"""
Purpose: Data models for requests
"""
from datetime import date
from typing import Optional

from pydantic import BaseModel, constr


# Conversation
class ConversationCreate(BaseModel):
    title: Optional[str] = None
    user_id: str


class ConversationUpdate(BaseModel):
    title: Optional[str] = None


class UserCreate(BaseModel):
    id: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    metadata: Optional[dict] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    metadata: Optional[dict] = None


# Message
class MessageCreate(BaseModel):
    content: constr(min_length=1)


# Feedback
class FeedbackCreate(BaseModel):
    type: str  # "like" | "dislike"
    comment: Optional[str] = None
