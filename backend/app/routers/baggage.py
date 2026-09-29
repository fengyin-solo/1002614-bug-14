"""行李装卸接口：转盘矩阵、列表筛选分页与单条读写都走同一套业务规则。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult, VersionedPayload
from app.services.baggage import SORT_ORDERS, UNASSIGNED_CAROUSEL, BaggageService

router = APIRouter(prefix="/api/baggage", tags=["行李装卸"])

service = BaggageService()


@router.get("/carousels")
def carousel_matrix() -> dict[str, Any]:
    """转盘矩阵：每个到达转盘一格，缺到达转盘的记录归入「未分配」格，计数与列表同源。"""
    return service.carousel_matrix()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出行李装卸清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "baggage", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    flight: str | None = Query(default=None, description="按对应航班检索"),
    carousel: str | None = Query(default=None, description=f"按到达转盘过滤；{UNASSIGNED_CAROUSEL} 表示缺到达转盘的记录"),
    status: str | None = Query(default=None, description="待装卸、装卸中、已交付、异常中断"),
    sort: str = Query(default="asc", description="按航班号排序：asc 或 desc"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """先按转盘过滤，再按航班号检索，排序之后分页；缺到达转盘的记录不参与转盘匹配但不消失。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if sort not in SORT_ORDERS:
        raise HTTPException(status_code=400, detail="排序方式只支持 asc 或 desc")
    items, total = service.list_entries(
        keyword=keyword, flight=flight, carousel=carousel, status=status, sort=sort,
        page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条行李任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"行李任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记行李任务：同一任务编号只落库一次，重复登记返回已存在的记录而不是新增。"""
    entry, status, detail = service.create_entry(payload.values)
    if status == "missing":
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(detail)}")
    if status == "duplicate":
        return ActionResult(ok=False, message=f"任务编号 {detail} 已登记，未重复创建", entry=entry)
    return ActionResult(ok=True, message="行李任务已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: VersionedPayload) -> ActionResult:
    """保存行李任务：带版本号，两个窗口同时保存时后一次以先落库的那份为准。"""
    entry, status, message = service.update_entry(entry_id, payload.values, payload.version)
    if status == "missing":
        raise HTTPException(status_code=404, detail=message)
    if status == "conflict":
        raise HTTPException(status_code=409, detail={"message": message, "entry": entry})
    if status in ("invalid", "duplicate"):
        return ActionResult(ok=False, message=message, entry=entry)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条行李任务执行开始装卸、确认交付、登记异常；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
