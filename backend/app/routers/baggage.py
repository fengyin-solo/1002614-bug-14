"""行李装卸接口：转盘矩阵、航班号检索、排序分页、登记去重与并发冲突。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.baggage import BaggageService

router = APIRouter(prefix="/api/baggage", tags=["行李装卸"])

service = BaggageService()

LIST_FIELDS = ["任务编号", "对应航班", "行李类型", "装卸方向", "出发转盘", "到达转盘", "装卸班组", "任务状态"]
STATUSES = ["待装卸", "装卸中", "已交付", "异常中断"]
SORT_FIELDS = ["任务编号", "对应航班", "任务状态", "到达转盘"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按航班号检索"),
    status: str | None = Query(default=None, description="待装卸、装卸中、已交付、异常中断"),
    carousel: str | None = Query(default=None, description="按到达转盘过滤"),
    sort: str | None = Query(default=None, description="排序字段：任务编号、对应航班、任务状态、到达转盘"),
    order: str | None = Query(default=None, description="asc 或 desc"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """先按转盘过滤、再按航班号检索；分页时保持已选转盘与排序，缺到达转盘的记录不消失。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, carousel=carousel, sort=sort, order=order, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/matrix", response_model=dict)
def matrix(
    keyword: str | None = Query(default=None, description="按航班号检索"),
    status: str | None = Query(default=None, description="待装卸、装卸中、已交付、异常中断"),
) -> dict:
    """转盘矩阵：与列表同源，按到达转盘分组计数，另给缺到达转盘的记录留一组。"""
    carousels, unassigned, total = service.matrix(keyword=keyword, status=status)
    return {"carousels": carousels, "unassigned": unassigned, "total": total}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条行李任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"行李任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条行李任务；任务编号已存在时返回原记录，不重复落库。"""
    entry, missing, duplicated = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if duplicated:
        return ActionResult(ok=True, message="该任务已登记，未重复创建，已为你定位到原记录", entry=entry)
    return ActionResult(ok=True, message="行李任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """执行开始装卸、确认交付、登记异常；版本号对不上时返回 409，以先落库的版本为准。"""
    action = str(payload.values.get("action") or "").strip()
    version = payload.values.get("version")
    entry, message, conflict = service.run_action(entry_id, action, version=version)
    if conflict:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "message": message, "entry": entry},
        )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出行李装卸清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "baggage", "total": total, "items": items}
