<script setup>
import { computed, onMounted, ref } from 'vue'
import { getJSON, postJSON, putJSON } from '../api'

const accounts = ref([])
const plans = ref([])
const runs = ref([])
const error = ref('')
const notice = ref('')

const blank = () => ({ id: null, name: '', master_account_id: null, remainder_account_id: null, members: [] })
const editor = ref(null)

const execPlanId = ref(null)
const period = ref(new Date().toISOString().slice(0, 7))
const force = ref(false)
const masterKwh = ref(null)
const result = ref(null)

const accountName = (id) => accounts.value.find((a) => a.id === id)?.name || `#${id}`
const editorSum = computed(() => (editor.value?.members || []).reduce((s, m) => s + (Number(m.pct) || 0), 0))
const execPlan = computed(() => plans.value.find((p) => p.id === execPlanId.value))

const load = async () => {
  accounts.value = (await getJSON('/api/accounts')).items
  plans.value = (await getJSON('/api/share/plans')).items
  runs.value = (await getJSON('/api/share/runs')).items
  if (!execPlanId.value && plans.value.length) execPlanId.value = plans.value[0].id
}
onMounted(load)

const guard = async (fn) => {
  error.value = ''
  notice.value = ''
  try {
    await fn()
  } catch (e) {
    error.value = e.message
  }
}

const newPlan = () => { editor.value = blank() }
const editPlan = (p) => {
  editor.value = {
    id: p.id,
    name: p.name,
    master_account_id: p.master_account_id,
    remainder_account_id: p.remainder_account_id,
    members: p.members.map((m) => ({ account_id: m.account_id, pct: m.pct })),
  }
}
const addMember = () => editor.value.members.push({ account_id: null, pct: null })
const removeMember = (i) => editor.value.members.splice(i, 1)

const savePlan = () => guard(async () => {
  const body = {
    name: editor.value.name,
    master_account_id: editor.value.master_account_id,
    remainder_account_id: editor.value.remainder_account_id,
    members: editor.value.members.map((m) => ({ account_id: m.account_id, pct: m.pct })),
  }
  const saved = editor.value.id
    ? await putJSON(`/api/share/plans/${editor.value.id}`, body)
    : await postJSON('/api/share/plans', body)
  notice.value = `方案【${saved.name}】已保存`
  editor.value = null
  await load()
})

const enterMasterKwh = () => guard(async () => {
  if (!execPlan.value) return
  await postJSON('/api/readings', {
    account_id: execPlan.value.master_account_id,
    kwh: masterKwh.value,
    peak: false,
    period: period.value,
  })
  notice.value = `已录入主表户【${execPlan.value.master_name}】${period.value} 电量 ${masterKwh.value} kWh`
})

const runExecute = () => guard(async () => {
  result.value = await postJSON('/api/share/execute', {
    plan_id: execPlanId.value,
    period: period.value,
    force: force.value,
  })
  notice.value = `账期 ${period.value} 分摊完成（记录#${result.value.id}）`
  await load()
})
</script>

<template>
  <div class="page">
    <h1>合表电量分摊</h1>
    <p v-if="error" class="msg err">⚠ {{ error }}</p>
    <p v-if="notice" class="msg ok">✓ {{ notice }}</p>

    <div class="panel">
      <h3>分摊方案 <button class="mini" @click="newPlan">新建方案</button></h3>
      <table>
        <thead><tr><th>名称</th><th>主表来源户</th><th>成员比例</th><th>余数归属</th><th></th></tr></thead>
        <tbody>
          <tr v-for="p in plans" :key="p.id">
            <td>{{ p.name }}</td>
            <td>{{ p.master_name }}</td>
            <td>
              <span v-for="m in p.members" :key="m.account_id" class="tag">{{ m.name }} {{ m.pct }}%</span>
            </td>
            <td>{{ accountName(p.remainder_account_id) }}</td>
            <td><a href="javascript:;" @click="editPlan(p)">编辑</a></td>
          </tr>
          <tr v-if="!plans.length"><td colspan="5" class="muted">暂无方案，点击“新建方案”</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="editor" class="panel">
      <h3>{{ editor.id ? `编辑方案 #${editor.id}` : '新建方案' }}</h3>
      <div class="form-row">
        <label>方案名称 <input v-model.trim="editor.name" placeholder="如：家属院合表" /></label>
        <label>主表来源户
          <select v-model.number="editor.master_account_id">
            <option :value="null" disabled>选择户号</option>
            <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </label>
      </div>
      <table>
        <thead><tr><th>成员户</th><th>比例(%)</th><th>余数归属</th><th></th></tr></thead>
        <tbody>
          <tr v-for="(m, i) in editor.members" :key="i">
            <td>
              <select v-model.number="m.account_id">
                <option :value="null" disabled>选择户号</option>
                <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
              </select>
            </td>
            <td><input type="number" v-model.number="m.pct" min="1" max="100" step="1" class="pct" /></td>
            <td><input type="radio" name="remainder" :value="m.account_id" v-model="editor.remainder_account_id" /></td>
            <td><a href="javascript:;" @click="removeMember(i)">移除</a></td>
          </tr>
        </tbody>
      </table>
      <div class="form-row">
        <button class="mini" @click="addMember">添加成员</button>
        <span :class="editorSum === 100 ? 'ok-text' : 'err-text'">比例合计 {{ editorSum }}%（须恰好 100%）</span>
        <button @click="savePlan">保存方案</button>
        <a href="javascript:;" @click="editor = null">取消</a>
      </div>
    </div>

    <div class="panel">
      <h3>按账期执行分摊</h3>
      <div class="form-row">
        <label>方案
          <select v-model.number="execPlanId">
            <option v-for="p in plans" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </label>
        <label>账期 <input type="month" v-model="period" /></label>
        <label>主表电量(kWh) <input type="number" v-model.number="masterKwh" min="0" step="0.001" class="kwh" /></label>
        <button class="mini" @click="enterMasterKwh" :disabled="!execPlan || masterKwh == null">录入主表电量</button>
        <label><input type="checkbox" v-model="force" /> force 重算</label>
        <button @click="runExecute" :disabled="!execPlanId">执行分摊</button>
      </div>
      <div v-if="result">
        <table>
          <thead><tr><th>成员户</th><th>比例</th><th>分摊电量(kWh)</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-for="a in result.allocations" :key="a.reading_id">
              <td>{{ a.name }}</td>
              <td>{{ a.pct }}%</td>
              <td>{{ a.kwh }}</td>
              <td><span class="tag share">分摊#{{ result.id }}</span></td>
            </tr>
          </tbody>
        </table>
        <p v-if="result.reconcile.balanced" class="ok-text">
          ✓ 对账平衡：主表 {{ result.reconcile.master_kwh }} kWh = 成员分摊之和 {{ result.reconcile.allocated_sum }} kWh
          <span class="muted">（余数 {{ result.reconcile.remainder_kwh }} kWh → {{ accountName(result.reconcile.remainder_account_id) }}）</span>
        </p>
        <p v-else class="err-text">✗ 对账差异 {{ result.reconcile.diff }} kWh</p>
      </div>
    </div>

    <div class="panel">
      <h3>分摊记录</h3>
      <table>
        <thead><tr><th>#</th><th>方案</th><th>账期</th><th>主表电量</th><th>分摊合计</th><th>余数</th><th>状态</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.plan_name }}</td>
            <td>{{ r.period }}</td>
            <td>{{ r.master_kwh }}</td>
            <td>{{ r.allocated_kwh }}</td>
            <td>{{ r.remainder_kwh }} → {{ accountName(r.remainder_account_id) }}</td>
            <td>
              <span v-if="r.status === 'active'" class="ok-text">有效</span>
              <span v-else class="muted">已作废→#{{ r.superseded_by }}</span>
            </td>
            <td class="muted">{{ r.created_at?.slice(0, 19).replace('T', ' ') }}</td>
          </tr>
          <tr v-if="!runs.length"><td colspan="8" class="muted">暂无分摊记录</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.form-row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: end; margin: 0.6rem 0; }
select { background: #0d1612; border: 1px solid var(--muted); color: var(--text); padding: 0.35rem 0.5rem; border-radius: 6px; }
input.pct { width: 5rem; }
input.kwh { width: 7rem; }
button.mini { padding: 0.25rem 0.6rem; font-size: 0.85rem; }
button:disabled { opacity: 0.45; cursor: not-allowed; }
.tag { background: color-mix(in srgb, var(--accent) 16%, transparent); border-radius: 6px; padding: 0.1rem 0.45rem; margin-right: 0.3rem; white-space: nowrap; }
.tag.share { color: var(--accent); }
.msg.err, .err-text { color: #ff8a8a; }
.ok-text { color: var(--accent); }
.msg { margin: 0.4rem 0; }
</style>
