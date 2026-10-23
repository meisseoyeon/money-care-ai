from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import CORS_ORIGINS
from app.health.router import router as health_router
from app.auth.router import router as auth_router
from app.demo.router import router as demo_router
from app.accounts.router import router as accounts_router
from app.recipients.router import router as recipients_router
from app.monitoring.router import router as monitoring_router
from app.transactions.router import router as transactions_router
from app.baselines.router import router as baselines_router
from app.budgets.router import router as budgets_router
from app.alerts.router import router as alerts_router
from app.supporters.router import router as supporters_router

app = FastAPI(title="Money Care AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(demo_router)
app.include_router(accounts_router)
app.include_router(recipients_router)
app.include_router(monitoring_router)
app.include_router(transactions_router)
app.include_router(baselines_router)
app.include_router(budgets_router)
app.include_router(alerts_router)
app.include_router(supporters_router)
