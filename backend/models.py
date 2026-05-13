from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


# ---- Auth ----
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str
    phone: Optional[str] = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class InviteIn(BaseModel):
    email: EmailStr
    role: str  # coach | parent
    name: Optional[str] = ""


class AcceptInviteIn(BaseModel):
    password: str = Field(min_length=6)
    name: Optional[str] = None
    phone: Optional[str] = ""


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    password: str = Field(min_length=6)


# ---- Sessions ----
class SessionIn(BaseModel):
    name: str
    skill_level: str  # beginner | intermediate | advanced
    age_group: str
    start_date: str  # YYYY-MM-DD
    end_date: str
    days_of_week: List[str]
    start_time: str  # HH:MM
    end_time: str
    location: str
    max_students: int
    monthly_price: float
    coach_id: Optional[str] = None
    status: str = "active"


# ---- Students ----
class StudentIn(BaseModel):
    first_name: str
    last_name: str
    dob: str
    skill_level: str = "beginner"
    emergency_contact_name: str
    emergency_contact_phone: str
    medical_notes: Optional[str] = ""
    waiver_accepted: bool = False
    t_shirt_size: Optional[str] = ""
    previous_experience: Optional[str] = ""


# ---- Enrollments ----
class EnrollmentIn(BaseModel):
    session_id: str
    student_id: str
    billing_type: Optional[str] = "Standard"  # Standard | NoCharge | Waived


class TransferIn(BaseModel):
    to_session_id: str
    effective_month: str  # YYYY-MM
    permanent: bool = True
    note: Optional[str] = ""


# ---- Attendance ----
class AttendanceItem(BaseModel):
    student_id: str
    status: str  # present | absent | late | excused | make_up
    notes: Optional[str] = ""


class AttendanceBulkIn(BaseModel):
    session_id: str
    date: str  # YYYY-MM-DD
    items: List[AttendanceItem]


# ---- Payments ----
class PaymentIn(BaseModel):
    enrollment_id: str
    period: str  # YYYY-MM
    amount: float
    discount: float = 0
    notes: Optional[str] = ""


class MarkPaidIn(BaseModel):
    payment_method: str = "cash"
    payment_date: Optional[str] = None
    notes: Optional[str] = ""


class DiscountIn(BaseModel):
    discount: float


class GenerateMonthlyIn(BaseModel):
    period: str  # YYYY-MM


# ---- Expenses ----
class ExpenseIn(BaseModel):
    category: str
    description: str
    amount: float
    date: str
    paid_to: Optional[str] = ""
    status: str = "paid"
    notes: Optional[str] = ""


# ---- Payout rules ----
class PayoutRuleIn(BaseModel):
    coach_id: str
    rule_type: str  # revenue_percentage | fixed_per_class | fixed_monthly | per_student
    value: float


class CalcPayoutIn(BaseModel):
    period: str  # YYYY-MM


# ---- Lesson plans / progress ----
class LessonPlanIn(BaseModel):
    session_id: str
    date: str
    objective: str
    warmup: Optional[str] = ""
    skill_drill: Optional[str] = ""
    game_activity: Optional[str] = ""
    fitness_activity: Optional[str] = ""
    homework: Optional[str] = ""
    coach_notes: Optional[str] = ""


class ProgressNoteIn(BaseModel):
    student_id: str
    session_id: Optional[str] = None
    note: str


# ---- Messages ----
class MessageIn(BaseModel):
    to_user_id: str
    body: str


# ---- Users ----
class UpdateUserIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    status: Optional[str] = None


class ResetUserPasswordIn(BaseModel):
    password: str = Field(min_length=6)
