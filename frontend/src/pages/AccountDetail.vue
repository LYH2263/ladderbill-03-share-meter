<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getJSON, postJSON } from '../api'
import SegmentTable from '../components/SegmentTable.vue'
const route = useRoute()
const data = ref(null)
const bill = ref(null)
const peak = ref(false)
const load = async () => {
  data.value = await getJSON(`/api/accounts/${route.params.id}`)
  const r = data.value.readings[0]
  if (r) bill.value = await postJSON('/api/bill', { account_id: +route.params.id, kwh: r.kwh, peak: !!r.peak, persist: false })
}
onMounted(load)
watch(() => route.params.id, load)
const account = computed(() => data.value?.account)
</script>
<template>
  <div class="page" v-if="account">
    <h1>{{ account.name }}</h1>
    <p class="muted">表号 {{ account.meter_no }} · {{ account.note }}</p>
    <div class="panel">
      <h3>最近抄表试算</h3>
      <label><input type="checkbox" v-model="peak" @change="bill = null" /> 尖峰</label>
      <button @click="load">刷新</button>
      <p v-if="bill">合计 <strong class="hero-num" style="font-size:1.5rem">¥{{ bill.total }}</strong></p>
      <SegmentTable :rows="bill?.segments || []" />
    </div>
    <div class="panel">
      <h3>抄表记录</h3>
      <table>
        <thead><tr><th>#</th><th>账期</th><th>电量(kWh)</th><th>尖峰</th><th>来源</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="r in data.readings" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.period || '—' }}</td>
            <td>{{ r.kwh }}</td>
            <td>{{ r.peak ? '是' : '否' }}</td>
            <td>
              <span v-if="r.source === 'share'" class="tag-share">分摊#{{ r.share_run_id }}</span>
              <span v-else class="muted">手动</span>
            </td>
            <td>
              <span v-if="r.superseded" class="muted">已作废</span>
              <span v-else>有效</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
<style scoped>
.tag-share { color: var(--accent); background: color-mix(in srgb, var(--accent) 16%, transparent); border-radius: 6px; padding: 0.1rem 0.45rem; }
</style>
