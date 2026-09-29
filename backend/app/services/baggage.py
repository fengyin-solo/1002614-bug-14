"""行李装卸业务规则：状态流转、字段校验与筛选口径都收在这里。

筛选、排序、分页是一条流水线：先按转盘过滤，再按航班号检索，然后排序，最后才分页。
列表接口和转盘矩阵共用这条流水线，保证两个界面看到的转盘与计数完全一致。
"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "baggage"
REQUIRED_FIELDS = ["任务编号", "对应航班", "行李类型"]
EDITABLE_FIELDS = REQUIRED_FIELDS + ["装卸方向", "出发转盘", "到达转盘", "装卸班组"]
STATUS_ORDER = ["待装卸", "装卸中", "已交付", "异常中断"]
ACTION_RULES = {"开始装卸": "装卸中", "确认交付": "已交付", "登记异常": "异常中断"}
UNASSIGNED_CAROUSEL = "未分配"
SORT_ORDERS = ("asc", "desc")


def _carousel_of(row: dict[str, Any]) -> str:
    return str(row.get("到达转盘") or "").strip()


def _task_no_of(row: dict[str, Any]) -> str:
    return str(row.get("任务编号") or "").strip()


class BaggageService:
    """行李装卸的查询流水线、转盘矩阵与并发保存规则。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ---- 查询流水线：过滤 → 检索 → 排序 → 分页，顺序不能乱 ----

    def _filtered_rows(
        self,
        *,
        keyword: str | None = None,
        flight: str | None = None,
        carousel: str | None = None,
        status: str | None = None,
        sort: str = "asc",
    ) -> list[dict[str, Any]]:
        rows = list(store.rows(MODULE))
        # 1) 先按转盘过滤：缺到达转盘的记录不参与转盘匹配，
        #    只在选「未分配」或不设转盘条件时出现，不会因为翻页而消失。
        if carousel == UNASSIGNED_CAROUSEL:
            rows = [row for row in rows if not _carousel_of(row)]
        elif carousel:
            rows = [row for row in rows if _carousel_of(row) == carousel]
        # 2) 再按航班号检索
        if flight:
            rows = [row for row in rows if flight in str(row.get("对应航班", ""))]
        # 3) 兼容旧的任务编号关键字与状态条件
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 4) 排序：按航班号，升降序可选；先按 id 排一次，保证同航班时顺序稳定
        rows.sort(key=lambda row: int(row.get("id", 0)))
        rows.sort(key=lambda row: str(row.get("对应航班") or ""), reverse=sort == "desc")
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        flight: str | None = None,
        carousel: str | None = None,
        status: str | None = None,
        sort: str = "asc",
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filtered_rows(
            keyword=keyword, flight=flight, carousel=carousel, status=status, sort=sort,
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    # ---- 转盘矩阵：与列表同一条流水线，只是不分页、按转盘分格 ----

    def carousel_matrix(self) -> dict[str, Any]:
        rows = self._filtered_rows()
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            buckets.setdefault(_carousel_of(row) or UNASSIGNED_CAROUSEL, []).append(row)
        cells: list[dict[str, Any]] = []
        for name in sorted(buckets, key=lambda n: (n == UNASSIGNED_CAROUSEL, n)):
            members = buckets[name]
            cells.append({
                "carousel": name,
                "unassigned": name == UNASSIGNED_CAROUSEL,
                "total": len(members),
                "remaining": sum(1 for row in members if row.get("status") in STATUS_ORDER[:2]),
                "byStatus": {s: sum(1 for row in members if row.get("status") == s) for s in STATUS_ORDER},
            })
        return {"cells": cells, "summary": self.summary()}

    def summary(self) -> dict[str, Any]:
        """任务计数：页面统计卡、转盘矩阵与运营概览都从这里取数，保证同源。"""
        rows = store.rows(MODULE)
        by_status = {s: sum(1 for row in rows if row.get("status") == s) for s in STATUS_ORDER}
        return {
            "total": len(rows),
            "pending": sum(1 for row in rows if row.get("pending")),
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
            "remaining": by_status["待装卸"] + by_status["装卸中"],
            "byStatus": by_status,
        }

    def overview_summary(self) -> dict[str, int]:
        """给运营概览用的口径：字段名对齐通用汇总，数字来自 summary()。"""
        summary = self.summary()
        return {
            "created": summary["total"],
            "pending": summary["pending"],
            "abnormal": summary["abnormal"],
        }

    # ---- 单条读写 ----

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def _find_by_task_no(self, task_no: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if _task_no_of(row) == task_no:
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, Any]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, "missing", missing
        task_no = _task_no_of(values)
        with self._lock:
            # 同一张任务登记两次不多出记录：命中已有编号时直接返回原记录
            existing = self._find_by_task_no(task_no)
            if existing is not None:
                return existing, "duplicate", task_no
            rows = store.rows(MODULE)
            entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in EDITABLE_FIELDS:
                entry[field] = values.get(field)
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            entry["version"] = 0
            rows.append(entry)
            return entry, "created", []

    def update_entry(
        self, entry_id: int, values: dict[str, Any], version: int,
    ) -> tuple[dict[str, Any] | None, str, str]:
        with self._lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, "missing", f"行李任务 {entry_id} 不存在或已归档"
            current = int(entry.get("version", 0))
            if current != version:
                # 两个窗口同时保存：后一次不覆盖先落库的内容，把已落库的记录带回去
                return entry, "conflict", "该任务刚在其他窗口保存过，已按先落库的内容刷新，请确认后再改"
            task_no = _task_no_of(values) if "任务编号" in values else _task_no_of(entry)
            if not task_no:
                return entry, "invalid", "任务编号不能为空"
            owner = self._find_by_task_no(task_no)
            if owner is not None and int(owner.get("id", 0)) != entry_id:
                return entry, "duplicate", f"任务编号 {task_no} 已被其他记录使用"
            for field in EDITABLE_FIELDS:
                if field in values:
                    entry[field] = values[field]
            entry["version"] = current + 1
            return entry, "ok", "行李任务已保存"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"行李任务 {entry_id} 不存在或已归档"
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于行李装卸可执行范围"
            target = ACTION_RULES[action]
            if target not in STATUS_ORDER:
                return None, f"目标状态「{target}」不在允许的状态序列里"
            entry["status"] = target
            entry["pending"] = target in STATUS_ORDER[:2]
            entry["abnormal"] = target == "异常中断"
            entry["version"] = int(entry.get("version", 0)) + 1
            return entry, f"行李任务已{action}"
