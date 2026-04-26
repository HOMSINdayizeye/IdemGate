from pydantic import BaseModel, Field


class PaymentRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Payment amount, must be greater than 0")
    currency: str = Field(..., min_length=1, description="Currency code e.g. GHS, USD")


class PaymentResponse(BaseModel):
    status: str
    message: str
    transaction_id: str
    amount: float
    currency: str
    processed_at: str
