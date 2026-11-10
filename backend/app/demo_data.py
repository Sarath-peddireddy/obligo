"""Fictional records copied into a new guest workspace within its creation transaction."""
from datetime import timedelta

from sqlalchemy.orm import Session

from app.deadlines import workspace_today
from app.models import Contract, Obligation


def seed_demo_workspace(db: Session, workspace_id: str) -> None:
    today = workspace_today()
    vendors = [
        ("Northstar Cloud", "Cloud infrastructure agreement", 172, 60),
        ("Meridian Analytics", "Data platform subscription", 92, 30),
        ("Harbor Legal", "Legal services retainer", 245, 90),
        ("Atlas Security", "Security monitoring services", 64, 45),
        ("Cedar Workplace", "Office facilities agreement", 315, 60),
        ("Summit Payments", "Payment processing agreement", 130, 30),
        ("Brightline Design", "Creative services agreement", 205, 45),
        ("Clearwater Logistics", "Distribution services agreement", 48, 30),
    ]
    tasks = [
        ("Review renewal terms", "Assess pricing and renewal options with the vendor.", "Legal", "pending_review", 20),
        ("Confirm insurance coverage", "Verify that the insurance certificate meets contract requirements.", "Operations", "overdue", -5),
        ("Submit usage report", "Send the latest usage report to the vendor contact.", "Finance", "due_today", 0),
        ("Approve quarterly invoice", "Review charges and approve the invoice for payment.", "Finance", "due_soon", 4),
        ("Schedule service review", "Arrange a review of service levels and open issues.", "Operations", "upcoming", 28),
        ("File compliance certificate", "File the signed certificate in the contract record.", "Compliance", "completed", -15),
        ("Confirm audit schedule", "Agree on an audit date with the vendor.", "Compliance", "unscheduled", None),
    ]
    for index, (vendor, title, renewal, notice) in enumerate(vendors):
        contract = Contract(workspace_id=workspace_id, vendor_name=vendor, title=f"[Sample] {title}",
                            renewal_date=today + timedelta(days=renewal), notice_period_days=notice,
                            source_clause="Fictional sample clause: the parties will review this agreement before renewal.")
        db.add(contract)
        for number in range(3):
            task, description, owner, status, offset = tasks[(index * 3 + number) % len(tasks)]
            db.add(Obligation(contract=contract, title=f"[Sample] {task}", description=description,
                              owner=owner, due_date=None if offset is None else today + timedelta(days=offset),
                              source_clause=f"Fictional sample clause: {description}",
                              review_status="pending_review" if status == "pending_review" else "approved",
                              is_completed=status == "completed"))
