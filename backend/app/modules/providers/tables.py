"""What real provider calls cost. Not linked to people or workspaces, and holds no text."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.model_mixins import UUIDPrimaryKeyMixin


class ProviderSpend(UUIDPrimaryKeyMixin, Base):
    """One call. The cost is the worst case until the call succeeds, then the real one."""

    __tablename__ = "provider_spend"
    __table_args__ = (
        CheckConstraint("cost_nano_usd >= 0", name="cost_not_negative"),
        Index("ix_provider_spend_created_at", "created_at"),
    )

    model: Mapped[str] = mapped_column(String(100), nullable=False)
    cost_nano_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Both empty = reserved: not finished, failed, cancelled or unclear.
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Set from app.core.clock (no server default) so that windows share one time source.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
