from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SignalAIExplanation(Base):
    __tablename__ = "signal_ai_explanations"
    __table_args__ = (
        CheckConstraint(
            "length(trim(model_provider)) > 0",
            name="ck_signal_ai_explanations_model_provider_not_blank",
        ),
        CheckConstraint("length(trim(model_name)) > 0", name="ck_signal_ai_explanations_model_name_not_blank"),
        CheckConstraint("length(trim(prompt_hash)) > 0", name="ck_signal_ai_explanations_prompt_hash_not_blank"),
        CheckConstraint(
            "length(trim(explanation_md)) > 0",
            name="ck_signal_ai_explanations_explanation_md_not_blank",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_signals.id", name="fk_signal_ai_explanations_signal_id", ondelete="CASCADE"),
        index=True,
    )
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(Text, nullable=False)
    explanation_md: Mapped[str] = mapped_column(Text, nullable=False)
    risk_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )

    signal: Mapped["TradingSignal"] = relationship(back_populates="ai_explanations")
