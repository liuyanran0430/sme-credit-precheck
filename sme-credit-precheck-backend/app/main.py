from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core import config
from app.core.exceptions import BusinessException
from app.core.logging import setup_logging
from app.db.init_db import init_db

OPENAPI_TAGS = [
    {"name": "系统", "description": "健康检查等系统级接口"},
    {"name": "认证", "description": "用户登录与身份认证"},
    {"name": "申请管理", "description": "授信申请提交、查询与状态流转"},
    {"name": "材料管理", "description": "申请材料上传、查询与删除"},
    {"name": "AI 预审", "description": "AI 预审报告查询与生成"},
    {"name": "人工复核", "description": "人工复核清单与复核结果提交"},
    {"name": "风控复核", "description": "风控复核队列与决策提交"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(debug=config.DEBUG)
    if config.DEBUG:
        init_db()
    yield


app = FastAPI(
    title=config.APP_NAME,
    version="0.1.0",
    description="小微企业授信智能预审系统后台接口。接口契约由 OpenAPI 自动生成。",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BusinessException)
async def business_exception_handler(request: Request, exc: BusinessException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.code,
        content={"code": exc.code, "message": exc.message},
    )


@app.get("/health", tags=["系统"], summary="健康检查")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router, prefix=config.API_V1_PREFIX)
