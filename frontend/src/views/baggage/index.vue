<template>
  <section class="page" data-module="baggage">
    <header class="page-head">
      <div>
        <h2>行李装卸管理</h2>
        <p class="page-desc">按到达转盘分格查看行李任务：交接时先看各转盘还剩几票，再点进格子逐条处理。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记行李任务</button>
        <button class="btn" type="button" @click="exportRows">导出行李装卸清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div v-if="matrixError" class="error-banner">
      <span>转盘矩阵暂时取不到数据：{{ matrixError }}</span>
      <button class="btn" type="button" @click="loadMatrix">重试</button>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>到达转盘</span>
        <select v-model="carousel" @change="onCarouselChange">
          <option value="">全部转盘</option>
          <option v-for="cell in cells" :key="cell.carousel" :value="cell.carousel">
            {{ cell.unassigned ? '未分配（缺到达转盘）' : cell.carousel }}
          </option>
        </select>
      </label>
      <label class="filter-item">
        <span>航班号</span>
        <input v-model.trim="flightDraft" placeholder="按航班号检索，如 CA1831" />
      </label>
      <label class="filter-item">
        <span>航班号排序</span>
        <select v-model="sort" @change="onSortChange">
          <option value="asc">升序</option>
          <option value="desc">降序</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="matrix">
      <button
        v-for="cell in matrixCells"
        :key="cell.carousel || '__all__'"
        type="button"
        class="matrix-cell"
        :class="{ active: carousel === cell.carousel, unassigned: cell.unassigned }"
        @click="selectCarousel(cell.carousel)"
      >
        <span class="cell-name">{{ cellName(cell) }}</span>
        <strong class="cell-remaining">剩 {{ cell.remaining }} 票</strong>
        <span class="cell-total">共 {{ cell.total }} 票</span>
      </button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column.label">{{ column.label }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column.label">{{ row[column.key] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">当前条件下没有行李装卸记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条行李装卸记录 · 第 {{ page }} / {{ pageCount }} 页</span>
      <span class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <button class="btn" type="button" :disabled="page >= pageCount" @click="goPage(page + 1)">下一页</button>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="dialog-mask" @click.self="closeDetail">
      <div class="dialog">
        <h3>行李任务 {{ detail.values['任务编号'] || detail.id }}</h3>
        <p v-if="detail.message" class="error-text">{{ detail.message }}</p>
        <label v-for="field in editableFields" :key="field" class="form-item">
          <span>{{ field }}</span>
          <input v-model="detail.values[field]" />
        </label>
        <p class="dialog-meta">当前状态：{{ detail.status }} · 数据版本 {{ detail.version }}</p>
        <div class="dialog-actions">
          <button class="btn primary" type="button" @click="saveDetail">保存</button>
          <button class="btn" type="button" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="createForm" class="dialog-mask" @click.self="createForm = null">
      <div class="dialog">
        <h3>登记行李任务</h3>
        <p v-if="createForm.message" class="error-text">{{ createForm.message }}</p>
        <label v-for="field in editableFields" :key="field" class="form-item">
          <span>{{ field }}</span>
          <input v-model="createForm.values[field]" :placeholder="`填写${field}`" />
        </label>
        <div class="dialog-actions">
          <button class="btn primary" type="button" @click="submitCreate">登记</button>
          <button class="btn" type="button" @click="createForm = null">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null | undefined>

interface MatrixCell {
  carousel: string
  unassigned: boolean
  total: number
  remaining: number
  byStatus: Record<string, number>
}

interface MatrixSummary {
  total: number
  pending: number
  abnormal: number
  remaining: number
  byStatus: Record<string, number>
}

interface DetailState {
  id: number
  values: Record<string, string>
  status: string
  version: number
  message: string
}

const ENDPOINT = '/api/baggage'
const PAGE_SIZE = 8
const STORAGE_KEY = 'baggage-carousel-view'
const columns = [
  { key: '任务编号', label: '任务编号' },
  { key: '对应航班', label: '对应航班' },
  { key: '行李类型', label: '行李类型' },
  { key: '装卸方向', label: '装卸方向' },
  { key: '出发转盘', label: '出发转盘' },
  { key: '到达转盘', label: '到达转盘' },
  { key: '装卸班组', label: '装卸班组' },
  { key: 'status', label: '任务状态' },
]
const actions = ['开始装卸', '确认交付', '登记异常']
const editableFields = ['任务编号', '对应航班', '行李类型', '装卸方向', '出发转盘', '到达转盘', '装卸班组']

const route = useRoute()
const router = useRouter()

// 筛选、排序、分页是同一份状态：进 URL 也进 sessionStorage，翻页或重开页面都不丢
const carousel = ref('')
const flight = ref('')
const flightDraft = ref('')
const sort = ref<'asc' | 'desc'>('asc')
const page = ref(1)

const cells = ref<MatrixCell[]>([])
const summary = ref<MatrixSummary | null>(null)
const rows = ref<Row[]>([])
const total = ref(0)
const matrixError = ref('')
const errorMessage = ref('')
const detail = ref<DetailState | null>(null)
const createForm = ref<{ values: Record<string, string>; message: string } | null>(null)

const stats = computed(() => {
  const byStatus = summary.value?.byStatus ?? {}
  return [
    { label: '待装卸航班', value: byStatus['待装卸'] ?? 0 },
    { label: '装卸中航班', value: byStatus['装卸中'] ?? 0 },
    { label: '已交付航班', value: byStatus['已交付'] ?? 0 },
    { label: '异常中断航班', value: byStatus['异常中断'] ?? 0 },
  ]
})

const matrixCells = computed<MatrixCell[]>(() => [
  {
    carousel: '',
    unassigned: false,
    total: summary.value?.total ?? 0,
    remaining: summary.value?.remaining ?? 0,
    byStatus: {},
  },
  ...cells.value,
])

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

function cellName(cell: MatrixCell) {
  if (!cell.carousel) return '全部转盘'
  return cell.unassigned ? '未分配转盘' : cell.carousel
}

function queryText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function restoreState() {
  const query = route.query
  if (['carousel', 'flight', 'sort', 'page'].some((key) => key in query)) {
    carousel.value = queryText(query.carousel)
    flight.value = queryText(query.flight)
    sort.value = query.sort === 'desc' ? 'desc' : 'asc'
    page.value = Math.max(1, Number(query.page) || 1)
  } else {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? 'null') as Record<string, unknown> | null
      if (saved) {
        carousel.value = queryText(saved.carousel)
        flight.value = queryText(saved.flight)
        sort.value = saved.sort === 'desc' ? 'desc' : 'asc'
        page.value = Math.max(1, Number(saved.page) || 1)
      }
    } catch {
      // 缓存损坏时按默认状态起步，不挡住页面
    }
  }
  flightDraft.value = flight.value
}

function syncState() {
  const query: Record<string, string> = {}
  if (carousel.value) query.carousel = carousel.value
  if (flight.value) query.flight = flight.value
  if (sort.value !== 'asc') query.sort = sort.value
  if (page.value > 1) query.page = String(page.value)
  void router.replace({ query })
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
    carousel: carousel.value,
    flight: flight.value,
    sort: sort.value,
    page: page.value,
  }))
  void loadList()
}

function selectCarousel(name: string) {
  carousel.value = carousel.value === name ? '' : name
  page.value = 1
  syncState()
}

function onCarouselChange() {
  page.value = 1
  syncState()
}

function onSortChange() {
  page.value = 1
  syncState()
}

function applyFilters() {
  flight.value = flightDraft.value
  page.value = 1
  syncState()
}

function resetFilters() {
  carousel.value = ''
  flight.value = ''
  flightDraft.value = ''
  sort.value = 'asc'
  page.value = 1
  syncState()
}

function goPage(next: number) {
  page.value = Math.min(Math.max(1, next), pageCount.value)
  syncState()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function loadMatrix() {
  matrixError.value = ''
  try {
    const response = await request(`${ENDPOINT}/carousels`)
    if (!response.ok) {
      throw new Error(`接口返回 ${response.status}`)
    }
    const payload = await response.json()
    cells.value = payload.cells ?? []
    summary.value = payload.summary ?? null
  } catch (error) {
    matrixError.value = error instanceof Error ? error.message : '转盘矩阵读取失败'
  }
}

async function loadList() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (carousel.value) params.set('carousel', carousel.value)
  if (flight.value) params.set('flight', flight.value)
  params.set('sort', sort.value)
  params.set('page', String(page.value))
  params.set('size', String(PAGE_SIZE))
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('行李任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (page.value > pageCount.value) {
      // 数据变少导致当前页超出范围时退回最后一页，而不是显示空页
      page.value = pageCount.value
      syncState()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '行李装卸列表读取失败'
  }
}

async function refreshAll() {
  await Promise.all([loadMatrix(), loadList()])
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.message ?? payload?.detail ?? '行李装卸动作未生效，请稍后重试')
    }
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '行李装卸操作失败'
  }
}

function pickEditable(row: Row): Record<string, string> {
  const values: Record<string, string> = {}
  for (const field of editableFields) {
    values[field] = String(row[field] ?? '')
  }
  return values
}

function openDetail(row: Row) {
  detail.value = {
    id: Number(row.id),
    values: pickEditable(row),
    status: String(row.status ?? ''),
    version: Number(row.version ?? 0),
    message: '',
  }
}

function closeDetail() {
  detail.value = null
}

async function saveDetail() {
  const current = detail.value
  if (!current) return
  try {
    const response = await request(`${ENDPOINT}/${current.id}`, {
      method: 'PUT',
      body: JSON.stringify({ values: current.values, version: current.version }),
    })
    const payload = await response.json()
    if (response.status === 409) {
      // 另一个窗口先落库了：以先落库的为准，把持久化的内容刷进表单
      const persisted = payload?.detail?.entry
      if (persisted) {
        current.values = pickEditable(persisted)
        current.status = String(persisted.status ?? current.status)
        current.version = Number(persisted.version ?? current.version)
      }
      current.message = payload?.detail?.message ?? '该任务刚在其他窗口保存过，已按先落库的内容刷新'
      await refreshAll()
      return
    }
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.message ?? payload?.detail ?? '行李任务保存失败')
    }
    detail.value = null
    await refreshAll()
  } catch (error) {
    current.message = error instanceof Error ? error.message : '行李任务保存失败'
  }
}

function openCreate() {
  const values: Record<string, string> = {}
  for (const field of editableFields) {
    values[field] = ''
  }
  createForm.value = { values, message: '' }
}

async function submitCreate() {
  const form = createForm.value
  if (!form) return
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: form.values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      form.message = payload?.message ?? payload?.detail ?? '行李任务登记失败'
      if (payload?.entry) {
        // 同一任务编号已登记过：不再新增，直接打开已存在的那条
        createForm.value = null
        openDetail(payload.entry)
      }
      return
    }
    createForm.value = null
    await refreshAll()
  } catch (error) {
    form.message = error instanceof Error ? error.message : '行李任务登记失败'
  }
}

onMounted(() => {
  restoreState()
  void loadMatrix()
  void loadList()
})
</script>
