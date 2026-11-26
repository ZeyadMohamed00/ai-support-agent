import os
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

engine = create_engine(
    os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres@localhost/support"),
    pool_pre_ping=True,
)
Session = sessionmaker(engine, expire_on_commit=False)
now = lambda: datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "sup_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    order_no: Mapped[str] = mapped_column(String(16))
    customer: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20))
    delivered_days_ago: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eta_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total: Mapped[float] = mapped_column(Float)
    items: Mapped[str] = mapped_column(String(200))
    refunded: Mapped[bool] = mapped_column(Boolean, default=False)


class Conversation(Base):
    __tablename__ = "sup_conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    customer: Mapped[str] = mapped_column(String(120))
    created_at = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = "sup_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("sup_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(30), default="")
    created_at = mapped_column(DateTime(timezone=True), default=now)


class ToolLog(Base):
    __tablename__ = "sup_tool_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool: Mapped[str] = mapped_column(String(40))
    args: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0)
    created_at = mapped_column(DateTime(timezone=True), default=now)


class Approval(Base):
    __tablename__ = "sup_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[int] = mapped_column(Integer)
    customer: Mapped[str] = mapped_column(String(120))
    order_no: Mapped[str] = mapped_column(String(16))
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|approved|rejected
    created_at = mapped_column(DateTime(timezone=True), default=now)


class LlmUsage(Base):
    __tablename__ = "sup_llm_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purpose: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(60))
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)
    created_at = mapped_column(DateTime(timezone=True), default=now)


SEED = [
    ("A1001", "sara@example.com", "delivered", 5, None, 49.90, "Wireless Mouse"),
    ("A1002", "sara@example.com", "shipped", None, 2, 120.00, "Mechanical Keyboard"),
    ("A1005", "sara@example.com", "delivered", 3, None, 349.00, "Standing Desk"),
    ("A1003", "omar@example.com", "delivered", 45, None, 15.00, "USB Cable"),
    ("A1004", "omar@example.com", "processing", None, None, 300.00, "Monitor"),
]


def init():
    Base.metadata.create_all(engine)


def ensure_seed(db, client_id: str):
    if client_id.startswith("user:"):
        return  # real accounts start empty; only anonymous guests get demo data
    if db.query(Order).filter_by(client_id=client_id).first():
        return
    db.add_all(
        [
            Order(
                client_id=client_id,
                order_no=o,
                customer=c,
                status=s,
                delivered_days_ago=d,
                eta_days=e,
                total=t,
                items=i,
            )
            for o, c, s, d, e, t, i in SEED
        ]
    )
    db.commit()
