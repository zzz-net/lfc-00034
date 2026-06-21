from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from booking.database import init_db, close_db
from booking.errors import BookingError, ErrorCode
from booking.rooms import router as rooms_router
from booking.bookings import router as bookings_router
from booking.audit import router as audit_router
from booking.batch_takeover_api import router as snapshots_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    close_db()


app = FastAPI(
    title="社区活动室预约系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(rooms_router)
app.include_router(bookings_router)
app.include_router(audit_router)
app.include_router(snapshots_router)


@app.exception_handler(BookingError)
async def booking_error_handler(request: Request, exc: BookingError):
    content = {
        "error_code": exc.code,
        "message": exc.message,
    }
    if exc.extra:
        content.update(exc.extra)
    return JSONResponse(
        status_code=422,
        content=content,
    )


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
