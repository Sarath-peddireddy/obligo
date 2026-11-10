"""Deadline status for date-only obligations in the workspace timezone."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings


def workspace_today() -> date:
    return datetime.now(ZoneInfo(settings.workspace_timezone)).date()


def deadline_status(is_completed: bool, review_status: str, due_date: date | None, today: date) -> str:
    if is_completed:
        return "completed"
    if review_status != "approved":
        return "pending_review"
    if due_date is None:
        return "unscheduled"
    if due_date < today:
        return "overdue"
    if due_date == today:
        return "due_today"
    if due_date <= today + timedelta(days=7):
        return "due_soon"
    return "upcoming"
