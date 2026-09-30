<template>
  <section class="page" data-module="baggage">
    <header class="page-head">
      <div>
        <h2>行李装卸管理</h2>
        <p class="page-desc">按转盘矩阵查看行李分布，先选转盘再按航班号检索，翻页与排序都会保留。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记行李任务</button>
        <button class="btn" type="button" @click="exportRows">导出行李装卸清单</button>
      </div>
    </header>

    <!-- 转盘矩阵：与列表同源，按到达转盘分组计数 -->
    <div class="matrix-panel">
      <div class="matrix-head">
        <h3>转盘矩阵</h3>
        <span class="matrix-hint">点击格子按转盘过滤，再点一次取消</span>
        <button class="btn retry" type="button" @click="loadMatrix">重试</button>
      </div>
      <p v-if="matrixError" class="error-text matrix-error">转盘矩阵加载失败：{{ matrixError }}</p>
      <div class="matrix-grid">
        <button
          v-for="cell in matrixCells"
          :key="cell.name"
          type="button"
          class="matrix-cell"
          :class="{ active: cell.name === filters.carousel }"
          @click="selectCarousel(cell.name)"
        >
          <span class="cell-name">{{ cell.name }}</span>
          <span class="cell-count">{{ cell.count }} 票</span>
        </button>
        <button
          v-if="unassigned.count"
          type="button"
          class="matrix-cell unassigned"
          :class="{ active: filters.carousel === UNASSIGNED }"
          @click="selectCarousel(UNASSIGNED)"
        >
          <span class="cell-name">未分配到达转盘</span>
          <span class="cell-count">{{ unassigned.count }} 票</span>
        </button>
      </div>
    </div>

    <!-- 筛选栏：先按转盘过滤，再按航班号检索 -->
    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>到达转盘</span>
        <select v-model="filters.carousel">
          <option value="">全部转盘</option>
          <option v-for="name in carouselNames" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>航班号</span>
        <input v-model="filters.keyword" placeholder="按航班号检索" />
      </label>
      <label class="filter-item">
        <span>任务状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>排序字段</span>
        <select v-model="filters.sort">
          <option value="任务编号">任务编号</option>
          <option value="对应航班">航班号</option>
          <option value="任务状态">任务状态</option>
          <option value="到达转盘">到达转盘</option>
        </select>
      </label>
      <label class="filter-item">
        <span>顺序</span>
        <select v-model="filters.order">
          <option value="asc">升序</option>
          <option value="desc">降序</option>
        </select>
      </label>
      <button class="btn primary" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 列表 -->
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" class="clickable" @click="openDetail(row)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions" @click.stop>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无行李装卸数据，可先登记行李任务</td>
        </tr>
      </tbody>
    </table>

    <!-- 未分配到达转盘：不参与筛选但不允许消失 -->
    <section v-if="filters.carousel && filters.carousel !== UNASSIGNED && unassigned.count" class="unassigned-panel">
      <h3>未分配到达转盘（{{ unassigned.count }} 票）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in unassigned.rows" :key="String(row.id)" class="clickable" @click="openDetail(row)">
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条行李装卸记录</span>
      <div class="pagination">
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} 页</span>
        <button class="btn" type="button" :disabled="page * size >= total" @click="goPage(page + 1)">下一页</button>
        <select v-model.number="size" @change="onSizeChange">
          <option :value="10">10 条/页</option>
          <option :value="20">20 条/页</option>
          <option :value="50">50 条/页</option>
        </select>
      </div>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记弹窗 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <h3>登记行李任务</h3>
        <form @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field" class="filter-item">
            <span>{{ field }}</span>
            <input v-model="createForm[field]" :placeholder="`请输入${field}`" />
          </label>
          <p v-if="createError" class="error-text">{{ createError }}</p>
          <div class="modal-actions">
            <button class="btn primary" type="submit">提交登记</button>
            <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="detailRow" class="modal-mask" @click.self="detailRow = null">
      <div class="modal">
        <h3>行李任务详情</h3>
        <dl class="detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detailRow[column] ?? '—' }}</dd>
          </template>
          <dt>版本</dt>
          <dd>{{ detailRow.version ?? 1 }}</dd>
        </dl>
        <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
        <div class="modal-actions">
          <button
            v-for="action in actions"
            :key="action"
            class="btn"
            type="button"
            @click="runAction(action, detailRow)"
          >
            {{ action }}
          </button>
          <button class="btn ghost" type="button" @click="detailRow = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/baggage'
const UNASSIGNED = '__unassigned__'
const columns = ["任务编号", "对应航班", "行李类型", "装卸方向", "出发转盘", "到达转盘", "装卸班组", "任务状态"]
const actions = ["开始装卸", "确认交付", "登记异常"]
const statuses = ["待装卸", "装卸中", "已交付", "异常中断"]
const createFields = ["任务编号", "对应航班", "行李类型", "装卸方向", "出发转盘", "到达转盘", "装卸班组"]

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const errorMessage = ref('')
const matrixError = ref('')
const matrixCells = ref<{ name: string; count: number; rows: Row[] }[]>([])
const unassigned = ref<{ count: number; rows: Row[] }>({ count: 0, rows: [] })

const filters = reactive({
  carousel: '',
  keyword: '',
  status: '',
  sort: '任务编号',
  order: 'asc',
})

const showCreate = ref(false)
const createForm = reactive<Record<string, string>>({})
const createError = ref('')
const detailRow = ref<Row | null>(null)

const carouselNames = ref<string[]>([])

function initFromQuery() {
  const q = route.query
  filters.carousel = typeof q.carousel === 'string' ? q.carousel : ''
  filters.keyword = typeof q.keyword === 'string' ? q.keyword : ''
  filters.status = typeof q.status === 'string' ? q.status : ''
  filters.sort = typeof q.sort === 'string' ? q.sort : '任务编号'
  filters.order = typeof q.order === 'string' ? q.order : 'asc'
  page.value = q.page ? Number(q.page) || 1 : 1
  size.value = q.size ? Number(q.size) || 20 : 20
}

function syncQuery() {
  const query: Record<string, string> = {}
  if (filters.carousel) query.carousel = filters.carousel
  if (filters.keyword) query.keyword = filters.keyword
  if (filters.status) query.status = filters.status
  if (filters.sort && filters.sort !== '任务编号') query.sort = filters.sort
  if (filters.order && filters.order !== 'asc') query.order = filters.order
  if (page.value > 1) query.page = String(page.value)
  if (size.value !== 20) query.size = String(size.value)
  router.replace({ query })
}

async function loadMatrix() {
  matrixError.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  try {
    const response = await request(`${ENDPOINT}/matrix?${query.toString()}`)
    if (!response.ok) throw new Error(`矩阵接口返回 ${response.status}`)
    const payload = await response.json()
    matrixCells.value = payload.carousels ?? []
    unassigned.value = payload.unassigned ?? { count: 0, rows: [] }
    carouselNames.value = matrixCells.value.map((cell) => cell.name)
  } catch (error) {
    matrixError.value = error instanceof Error ? error.message : '转盘矩阵读取失败'
  }
}

async function loadList() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.carousel) query.set('carousel', filters.carousel)
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.sort) query.set('sort', filters.sort)
  if (filters.order) query.set('order', filters.order)
  query.set('page', String(page.value))
  query.set('size', String(size.value))
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('行李任务列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '行李装卸列表读取失败'
  }
}

function reload() {
  void Promise.all([loadMatrix(), loadList()])
}

function applyFilters() {
  page.value = 1
  syncQuery()
  reload()
}

function resetFilters() {
  filters.carousel = ''
  filters.keyword = ''
  filters.status = ''
  filters.sort = '任务编号'
  filters.order = 'asc'
  page.value = 1
  syncQuery()
  reload()
}

function selectCarousel(name: string) {
  filters.carousel = filters.carousel === name ? '' : name
  page.value = 1
  syncQuery()
  void loadList()
}

function goPage(target: number) {
  if (target < 1 || (target - 1) * size.value >= total.value) return
  page.value = target
  syncQuery()
  void loadList()
}

function onSizeChange() {
  page.value = 1
  syncQuery()
  void loadList()
}

function openCreate() {
  Object.keys(createForm).forEach((key) => { createForm[key] = '' })
  createError.value = ''
  showCreate.value = true
}

async function submitCreate() {
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? '行李任务登记失败')
    }
    showCreate.value = false
    await loadMatrix()
    await loadList()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '行李任务登记失败'
  }
}

function openDetail(row: Row) {
  detailRow.value = row
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, version: row.version ?? 1 } }),
    })
    const payload = await response.json().catch(() => null)
    if (response.status === 409) {
      errorMessage.value = payload?.message ?? '该任务已被其他窗口先保存，以先落库的版本为准'
      if (payload?.entry) detailRow.value = payload.entry
      await loadList()
      return
    }
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? '行李装卸动作未生效')
    }
    if (detailRow.value && detailRow.value.id === row.id && payload?.entry) {
      detailRow.value = payload.entry
    }
    await loadList()
    await loadMatrix()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '行李装卸操作失败'
  }
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

onMounted(() => {
  initFromQuery()
  reload()
})
</script>
