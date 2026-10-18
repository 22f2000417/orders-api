from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from threading import Lock
import time
import uuid
import hashlib
import json
import math

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

TOTAL_ORDERS = 42
RATE_LIMIT = 16
WINDOW_SECONDS = 10

orders = {}
idempotency_keys = {}
client_requests = {}
lock = Lock()


class OrderInput(BaseModel):
    product: str = "Product"
    quantity: int = 1


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id", "anonymous")
    now = time.monotonic()

    with lock:
        timestamps = client_requests.setdefault(client_id, [])
        timestamps[:] = [
            t for t in timestamps if now - t < WINDOW_SECONDS
        ]

        if len(timestamps) >= RATE_LIMIT:
            retry_after = max(
                1, math.ceil(WINDOW_SECONDS - (now - timestamps[0]))
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(retry_after),
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Expose-Headers": "Retry-After",
                },
            )

        timestamps.append(now)

    return await call_next(request)


@app.get("/")
def root():
    return {"status": "ok", "total_orders": TOTAL_ORDERS}


@app.get("/orders")
def list_orders(limit: int = 10, cursor: str = None):
    limit = max(1, min(limit, TOTAL_ORDERS))

    start = 0
    if cursor:
        try:
            decoded = int(cursor)
            start = decoded
        except (ValueError, TypeError):
            start = 0

    start = max(0, min(start, TOTAL_ORDERS))
    end = min(start + limit, TOTAL_ORDERS)

    items = [{"id": i} for i in range(start + 1, end + 1)]

    next_cursor = str(end) if end < TOTAL_ORDERS else None

    return {
        "items": items,
        "next_cursor": next_cursor
    }


@app.post("/orders", status_code=201)
def create_order(
    order: OrderInput,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    with lock:
        if idempotency_key in idempotency_keys:
            return idempotency_keys[idempotency_key]

        order_id = str(uuid.uuid4())
        result = {
            "id": order_id,
            "product": order.product,
            "quantity": order.quantity,
        }

        idempotency_keys[idempotency_key] = result
        orders[order_id] = result
        return result
