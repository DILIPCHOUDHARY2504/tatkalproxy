"""
Tatkal Proxy - Webhook API Server (FastAPI)
Exposes signed payment gateway callbacks and production Telegram webhook receiver.
"""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Request, Depends, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import settings
from database.connection import get_db
from services.gateway_service import gateway_service

logger = logging.getLogger("TatkalProxy.FastAPI")

app = FastAPI(
    title=settings.APP_NAME,
    description="Webhook API Server for Tatkal Proxy",
    version=settings.VERSION,
)


class GatewayPaymentWebhookPayload(BaseModel):
    order_code: str = Field(..., description="Internal Tatkal Proxy order code")
    payment_id: str = Field(..., description="External payment ID from gateway")
    amount: float = Field(..., gt=0, description="Amount received in INR")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "version": settings.VERSION,
    }


@app.get("/webapp/utr", response_class=HTMLResponse)
async def webapp_utr_modal(order_id: int):
    """
    Telegram Mini App modal for UTR submission.
    Renders input field, placeholder, Submit, and Cancel buttons.
    """
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
  <title>Enter Your UTR Number</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--tg-theme-bg-color, #17212b);
      color: var(--tg-theme-text-color, #ffffff);
      margin: 0;
      padding: 24px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 85vh;
      box-sizing: border-box;
    }}
    .card {{
      background: var(--tg-theme-secondary-bg-color, #232e3c);
      border-radius: 16px;
      padding: 24px;
      width: 100%;
      max-width: 380px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.35);
      text-align: center;
      box-sizing: border-box;
    }}
    h2 {{
      margin: 0 0 10px 0;
      font-size: 20px;
      color: var(--tg-theme-button-color, #5288c1);
    }}
    p {{
      margin: 0 0 20px 0;
      font-size: 13.5px;
      color: var(--tg-theme-hint-color, #8e9ca8);
      line-height: 1.4;
    }}
    input {{
      width: 100%;
      box-sizing: border-box;
      padding: 14px;
      border-radius: 10px;
      border: 1px solid #3c4c5e;
      background: #0e1621;
      color: #ffffff;
      font-size: 16px;
      text-align: center;
      letter-spacing: 1px;
      margin-bottom: 12px;
      outline: none;
    }}
    input:focus {{
      border-color: var(--tg-theme-button-color, #5288c1);
    }}
    .error-msg {{
      color: #e53935;
      font-size: 12.5px;
      margin-bottom: 15px;
      display: none;
    }}
    .btn-group {{
      display: flex;
      gap: 12px;
    }}
    button {{
      flex: 1;
      padding: 12px;
      border: none;
      border-radius: 10px;
      font-size: 14.5px;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.15s ease;
    }}
    button:active {{
      opacity: 0.8;
    }}
    .btn-cancel {{
      background-color: #384553;
      color: #c4d1de;
    }}
    .btn-submit {{
      background-color: var(--tg-theme-button-color, #2b73b8);
      color: var(--tg-theme-button-text-color, #ffffff);
    }}
  </style>
</head>
<body>
  <div class="card">
    <h2>Enter Your UTR Number</h2>
    <p>Enter your 12-digit UPI transaction reference number.</p>
    <input type="text" id="utrInput" placeholder="Enter your 12-digit UPI transaction reference number." maxlength="22" autocomplete="off" />
    <div id="errorMsg" class="error-msg"></div>
    <div class="btn-group">
      <button class="btn-cancel" onclick="cancelModal()">Cancel</button>
      <button class="btn-submit" onclick="submitModal()">Submit</button>
    </div>
  </div>

  <script>
    const tg = window.Telegram ? window.Telegram.WebApp : null;
    if (tg) {{
      tg.ready();
      tg.expand();
    }}

    function cancelModal() {{
      if (tg) {{
        tg.close();
      }} else {{
        window.close();
      }}
    }}

    function submitModal() {{
      const input = document.getElementById("utrInput");
      const err = document.getElementById("errorMsg");
      const clean = input.value.trim();

      if (!clean) {{
        err.innerText = "Please enter your UTR number.";
        err.style.display = "block";
        return;
      }}

      if (!/^[a-zA-Z0-9]{{8,22}}$/.test(clean)) {{
        err.innerText = "Invalid UTR format. Enter 12 alphanumeric characters.";
        err.style.display = "block";
        return;
      }}

      err.style.display = "none";
      if (tg) {{
        tg.sendData(JSON.stringify({{
          type: "utr_submission",
          order_id: {order_id},
          utr: clean
        }}));
        tg.close();
      }} else {{
        alert("Submitted UTR: " + clean);
      }}
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@app.post("/webhooks/payment")
async def handle_payment_gateway_webhook(
    request: Request,
    payload: GatewayPaymentWebhookPayload,
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
):
    """
    Handle incoming signed payment gateway webhooks.
    Validates HMAC signature, checks idempotency, and fulfills proxy delivery.
    """
    raw_body = await request.body()

    # Validate HMAC signature
    if not x_webhook_signature or not gateway_service.provider.verify_webhook_signature(
        raw_body, x_webhook_signature
    ):
        logger.warning("Payment webhook signature verification failed.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    # Process verified payment in DB transaction
    with get_db() as db:
        success, msg, data = await gateway_service.process_verified_webhook(
            db=db,
            order_code=payload.order_code,
            gateway_payment_id=payload.payment_id,
            amount_received=payload.amount,
            signature=x_webhook_signature,
            bot=None,  # Handled or injected
        )

        if not success:
            logger.error(f"Webhook processing error: {msg}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Webhook processing failed: {msg}",
            )

    return {"status": "success", "message": msg, "data": data}
