<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { getJSON, postJSON, putJSON } from '../api'

const accounts = ref([])
const schemes = ref([])
const allocations = ref([])
const loading = ref(false)

const accountName = (id) => accounts.value.find((a) => a.id === id)?.name || `户#${id}`
const accountMeter = (id) => accounts.value.find((a) => a.id === id)?.meter_no || '—'

// ---------- 方案编辑 ----------
const editing = ref(false)
const editId = ref(null)
const form = reactive({ name: '', master_account_id: null, remainder_account_id: null, members: [] })
const formError = ref('')

const ratioSum = computed(() => form.members.reduce((s, m) => s + (Number(m.ratio) || 0), 0))
const ratioSumOk = computed(() => ratioSum.value === 100)
const duplicateIds = computed(() => {
  const seen = new Set()
  const dup = new Set()
  for (const m of form.members) {
    if (m.account_id == null) continue
    if (seen.has(m.account_id)) dup.add(m.account_id)
    seen.add(m.account_id)
  }
  return dup
})
const formValid = computed(
  () =>
    form.name.trim() &&
    form.master_account_id != null &&
    form.remainder_account_id != null &&
    form.members.length >= 2 &&
    form.members.every((m) => m.account_id != null && m.ratio >= 1 && m.ratio <= 100) &&
    ratioSumOk.value &&
    duplicateIds.value.size === 0 &&
    form.members.some((m) => m.account_id === form.remainder_account_id)
)

function resetForm() {
  form.name = ''
  form.master_account_id = accounts.value[0]?.id ?? null
  form.remainder_account_id = form.master_account_id
  form.members = [
    { account_id: accounts.value[0]?.id ?? null, ratio: 50 },
    { account_id: accounts.value[1]?.id ?? null, ratio: 50 },
  ]
  formError.value = ''
}

function startCreate() {
  editId.value = null
  editing.value = true
  resetForm()
}

function startEdit(scheme) {
  editId.value = scheme.id
  editing.value = true
  form.name = scheme.name
  form.master_account_id = scheme.master_account_id
  form.remainder_account_id = scheme.remainder_account_id
  form.members = scheme.members.map((m) => ({ account_id: m.account_id, ratio: m.ratio }))
  formError.value = ''
}

function addMember() {
  form.members.push({ account_id: null, ratio: 0 })
}
function removeMember(idx) {
  const removed = form.members.splice(idx, 1)[0]
  if (removed.account_id === form.remainder_account_id) {
    form.remainder_account_id = form.members[0]?.account_id ?? null
  }
}

async function saveScheme() {
  formError.value = ''
  const payload = {
    name: form.name.trim(),
    master_account_id: form.master_account_id,
    remainder_account_id: form.remainder_account_id,
    members: form.members.map((m) => ({ account_id: m.account_id, ratio: Number(m.ratio) })),
  }
  try {
    if (editId.value) {
      await putJSON(`/api/share/schemes/${editId.value}`, payload)
    } else {
      await postJSON('/api/share/schemes', payload)
    }
    editing.value = false
    await loadSchemes()
  } catch (e) {
    formError.value = e.message
  }
}

// ---------- 按账期执行 ----------
const runForm = reactive({ scheme_id: null, period: '', master_kwh: 100, force: false })
const runError = ref('')
const lastResult = ref(null)

async function execute() {
  runError.value = ''
  lastResult.value = null
  try {
    lastResult.value = await postJSON('/api/share/allocations/run', {
      scheme_id: runForm.scheme_id,
      period: runForm.period,
      master_kwh: Number(runForm.master_kwh),
      force: runForm.force,
    })
    runForm.force = false
    await loadAllocations()
  } catch (e) {
    runError.value = e.message
  }
}

// ---------- 分摊记录 ----------
const expanded = ref(new Set())
function toggle(id) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}

async function loadSchemes() {
  schemes.value = (await getJSON('/api/share/schemes')).items
  // 拉取成员明细（列表接口不含 members）
  for (const s of schemes.value) {
    if (!s.members) s.members = (await getJSON(`/api/share/schemes/${s.id}`)).members
  }
  if (runForm.scheme_id == null && schemes.value[0]) runForm.scheme_id = schemes.value[0].id
  await loadAllocations()
}

async function loadAllocations() {
  const qs = runForm.scheme_id ? `?scheme_id=${runForm.scheme_id}` : ''
  allocations.value = (await getJSON(`/api/share/allocations${qs}`)).items
}

async function switchScheme() {
  runError.value = ''
  lastResult.value = null
  await loadAllocations()
}

onMounted(async () => {
  loading.value = true
  try {
    accounts.value = (await getJSON('/api/accounts')).items
    const now = new Date()
    runForm.period = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
    await loadSchemes()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page share">
    <h1>合表电量分摊</h1>
    <p class="muted">
      主表电量按整数百分比分摊到成员户抄表；比例之和须恰好 100，成员不得重复；
      除不尽的余数电量归指定成员。同账期重算将对旧分摊抄表做作废标记。
    </p>

    <!-- 方案列表 -->
    <div class="panel">
      <div class="panel-head">
        <h3>分摊方案</h3>
        <button @click="startCreate" v-if="!editing">新建方案</button>
      </div>

      <table v-if="schemes.length">
        <thead>
          <tr><th>方案</th><th>主表电量来源户</th><th>余数归属</th><th>成员 / 比例</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="s in schemes" :key="s.id">
            <td>{{ s.name }} <span class="muted">#{{ s.id }}</span></td>
            <td>{{ accountName(s.master_account_id) }} <span class="muted">{{ s.master_meter_no }}</span></td>
            <td>{{ accountName(s.remainder_account_id) }}</td>
            <td class="muted">
              {{ (s.members || []).map((m) => `${accountName(m.account_id)} ${m.ratio}%`).join('、') }}
            </td>
            <td><button class="ghost" @click="startEdit(s)">编辑</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">尚无方案，点击「新建方案」。</p>
    </div>

    <!-- 方案编辑 -->
    <div class="panel" v-if="editing">
      <h3>{{ editId ? `编辑方案 #${editId}` : '新建方案' }}</h3>
      <div class="form-grid">
        <label>方案名称
          <input v-model="form.name" maxlength="50" placeholder="例如：一号总表合摊" />
        </label>
        <label>主表电量来源户
          <select v-model="form.master_account_id">
            <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}（{{ a.meter_no }}）</option>
          </select>
        </label>
        <label>余数归属成员
          <select v-model="form.remainder_account_id">
            <option v-for="m in form.members.filter((x) => x.account_id != null)" :key="m.account_id" :value="m.account_id">
              {{ accountName(m.account_id) }}
            </option>
          </select>
        </label>
      </div>

      <h4>成员户与比例</h4>
      <table>
        <thead><tr><th>成员户</th><th style="width:9rem">比例(%)</th><th></th></tr></thead>
        <tbody>
          <tr v-for="(m, idx) in form.members" :key="idx">
            <td>
              <select v-model="m.account_id" :class="{ dup: duplicateIds.has(m.account_id) }">
                <option :value="null" disabled>选择户号</option>
                <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}（{{ a.meter_no }}）</option>
              </select>
              <span v-if="duplicateIds.has(m.account_id)" class="err">成员重复</span>
            </td>
            <td><input type="number" min="1" max="100" step="1" v-model.number="m.ratio" /></td>
            <td>
              <button class="ghost danger" @click="removeMember(idx)" :disabled="form.members.length <= 2">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="row-gap">
        <button class="ghost" @click="addMember">+ 添加成员</button>
        <span :class="ratioSumOk ? 'ok' : 'err'">
          比例之和：{{ ratioSum }}%（须恰好 100%）
        </span>
      </div>

      <p v-if="formError" class="err boxed">{{ formError }}</p>

      <div class="row-gap">
        <button @click="saveScheme" :disabled="!formValid">保存方案</button>
        <button class="ghost" @click="editing = false">取消</button>
        <span v-if="!formValid && !formError" class="muted">
          请补全成员、消除重复并使比例之和为 100
        </span>
      </div>
    </div>

    <!-- 按账期执行 -->
    <div class="panel">
      <h3>按账期执行分摊</h3>
      <div class="form-grid">
        <label>分摊方案
          <select v-model="runForm.scheme_id" @change="switchScheme">
            <option v-for="s in schemes" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </label>
        <label>账期
          <input type="month" v-model="runForm.period" />
        </label>
        <label>主表电量(kWh)
          <input type="number" min="0" step="0.001" v-model.number="runForm.master_kwh" />
        </label>
        <label class="force-line">
          <input type="checkbox" v-model="runForm.force" /> 强制重算（force）
        </label>
      </div>
      <div class="row-gap">
        <button @click="execute" :disabled="!runForm.scheme_id || !runForm.period || runForm.master_kwh < 0">
          执行分摊
        </button>
        <span v-if="runForm.force" class="warn">将对该账期旧分摊单及其抄表做「已作废」软标记，不会物理删除。</span>
      </div>
      <p v-if="runError" class="err boxed">{{ runError }}</p>

      <div v-if="lastResult" class="result">
        <h4>
          分摊单 #{{ lastResult.id }} · 账期 {{ lastResult.period }}
          <span v-if="lastResult.superseded_allocation_id" class="warn">
            已重算，旧分摊单 #{{ lastResult.superseded_allocation_id }} 及旧抄表已软标记作废
          </span>
        </h4>
        <table>
          <thead>
            <tr><th>成员户</th><th>比例</th><th>基准电量</th><th>余数电量</th><th>分摊电量</th></tr>
          </thead>
          <tbody>
            <tr v-for="l in lastResult.lines" :key="l.id" :class="{ owner: l.remainder_kwh > 0 }">
              <td>
                {{ accountName(l.account_id) }}
                <span v-if="l.account_id === lastResult.scheme.remainder_account_id" class="tag">余数归属</span>
              </td>
              <td>{{ l.ratio }}%</td>
              <td>{{ l.base_kwh }}</td>
              <td>{{ l.remainder_kwh }}</td>
              <td><strong>{{ l.allocated_kwh }}</strong></td>
            </tr>
          </tbody>
        </table>
        <div class="reconcile" :class="{ ok: lastResult.reconcile.balanced, bad: !lastResult.reconcile.balanced }">
          对账核验：主表电量 {{ lastResult.reconcile.master_kwh }} kWh ＝
          成员分摊之和 {{ lastResult.reconcile.member_sum }} kWh，
          差额 {{ lastResult.reconcile.difference }}
          <strong>{{ lastResult.reconcile.balanced ? ' ✓ 平衡' : ' ✗ 不平衡' }}</strong>
        </div>
      </div>
    </div>

    <!-- 分摊记录 -->
    <div class="panel">
      <h3>分摊记录</h3>
      <table v-if="allocations.length">
        <thead>
          <tr><th>账期</th><th>方案</th><th>主表电量</th><th>成员合计</th><th>状态</th><th></th></tr>
        </thead>
        <tbody>
          <template v-for="a in allocations" :key="a.id">
            <tr :class="{ dead: a.status !== 'active' }">
              <td>{{ a.period }}</td>
              <td>{{ a.scheme_name }} <span class="muted">#{{ a.id }}</span></td>
              <td>{{ a.master_kwh }}</td>
              <td>{{ a.lines.reduce((s, l) => s + l.allocated_kwh, 0).toFixed(3) }}</td>
              <td>
                <span :class="a.status === 'active' ? 'tag live' : 'tag dead'">
                  {{ a.status === 'active' ? '生效中' : '已作废' }}
                </span>
                <span v-if="a.superseded_by_id" class="muted"> → #{{ a.superseded_by_id }}</span>
              </td>
              <td><button class="ghost" @click="toggle(a.id)">{{ expanded.has(a.id) ? '收起' : '明细' }}</button></td>
            </tr>
            <tr v-if="expanded.has(a.id)">
              <td colspan="6">
                <table class="inner">
                  <tbody>
                    <tr v-for="l in a.lines" :key="l.id">
                      <td>{{ accountName(l.account_id) }}（{{ l.meter_no }}）</td>
                      <td>{{ l.ratio }}%</td>
                      <td>基准 {{ l.base_kwh }}</td>
                      <td>余数 {{ l.remainder_kwh }}</td>
                      <td>分摊 <strong>{{ l.allocated_kwh }}</strong></td>
                      <td class="muted">抄表 #{{ l.reading_id }}</td>
                    </tr>
                  </tbody>
                </table>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-else class="muted">该方案暂无分摊记录。</p>
    </div>
  </div>
</template>

<style scoped>
.panel-head { display: flex; justify-content: space-between; align-items: center; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 0.8rem; margin-bottom: 0.8rem; }
.form-grid label, .form-grid select, .form-grid input { width: 100%; }
.form-grid label { display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.9rem; color: var(--muted); }
.row-gap { display: flex; flex-wrap: wrap; gap: 0.8rem; align-items: center; margin-top: 0.7rem; }
button.ghost { background: transparent; color: var(--accent); border: 1px solid var(--accent); font-weight: 500; }
button.danger { color: #e88; border-color: #e88; }
button:disabled { opacity: 0.45; cursor: not-allowed; }
.err { color: #ff8a8a; }
.ok { color: var(--accent); }
.warn { color: #e8c46a; font-size: 0.88rem; }
.boxed { border: 1px solid #e88; border-radius: 8px; padding: 0.5rem 0.7rem; margin-top: 0.7rem; }
.dup { border-color: #e88 !important; }
.tag { font-size: 0.75rem; border: 1px solid currentColor; border-radius: 6px; padding: 0 0.35rem; margin-left: 0.35rem; }
.tag.live { color: var(--accent); }
.tag.dead { color: var(--muted); }
.owner td { background: color-mix(in srgb, var(--accent) 10%, transparent); }
.dead { opacity: 0.55; }
.reconcile { margin-top: 0.7rem; padding: 0.6rem 0.8rem; border-radius: 8px; }
.reconcile.ok { background: color-mix(in srgb, var(--accent) 14%, transparent); }
.reconcile.bad { background: color-mix(in srgb, #e88 18%, transparent); }
.inner { margin: 0.3rem 0 0.6rem; background: #0d1612; border-radius: 8px; }
.force-line { flex-direction: row !important; align-items: center; }
</style>
