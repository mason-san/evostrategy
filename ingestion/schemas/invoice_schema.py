from pydantic import BaseModel

class Invoice(BaseModel):
    invoice_number: str
    invoice_date: str
    total_amount: int 