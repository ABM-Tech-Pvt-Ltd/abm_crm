<template>
  <!-- abm_crm: idle-lead alert rules (API: abm_crm.api.idle_alerts) -->
  <div class="flex h-full flex-col gap-4 px-4 py-6 text-ink-gray-8 sm:px-6 sm:py-8">
    <div class="flex flex-wrap justify-between gap-3 px-2">
      <div class="flex flex-col gap-1">
        <h2 class="flex gap-2 text-2xl-semibold leading-none">{{ __('Idle Lead Alerts') }}</h2>
        <p class="max-w-2xl text-p-base text-ink-gray-6">
          {{ __('Notify people when a lead has had no activity for too long. Idle time counts only inside working hours: with hours 10:30 to 19:30, a lead that arrives at 20:00 starts its idle clock at 10:30 the next working day.') }}
        </p>
      </div>
      <Button v-if="tab === 'rules'" :label="__('New Rule')" iconLeft="plus" variant="solid" @click="openForm()" />
      <Button v-else :label="__('Refresh')" iconLeft="refresh-cw" @click="reloadTab" />
    </div>

    <div class="flex gap-1 border-b border-outline-gray-modals px-2">
      <button
        v-for="t in tabs"
        :key="t.key"
        class="-mb-px border-b-2 px-3 py-2 text-p-base"
        :class="tab === t.key ? 'border-ink-gray-9 font-medium text-ink-gray-9' : 'border-transparent text-ink-gray-5 hover:text-ink-gray-8'"
        @click="tab = t.key"
      >
        {{ __(t.label) }}
      </button>
    </div>

    <div v-if="setup.loading && !setup.data" class="mt-20 flex w-full">
      <Button :loading="true" variant="ghost" class="w-full" size="2xl" />
    </div>
    <ErrorMessage v-else-if="setup.error" class="px-2" :message="errText(setup.error)" />

    <!-- rules -->
    <div v-else-if="tab === 'rules'" class="flex flex-1 flex-col overflow-y-auto">
      <div v-if="!rules.length" class="px-2 py-8 text-center text-p-base text-ink-gray-5">
        {{ __('No alert rules yet. Create one, for example: leads in New or Contacted with no activity for 60 working minutes notify the owner, after 180 minutes notify the Sales Manager role.') }}
      </div>
      <template v-for="(rule, i) in rules" :key="rule.name">
        <div v-if="i" class="mx-2 h-px border-t border-outline-gray-modals" />
        <div class="flex items-center justify-between gap-3 px-2 py-3">
          <div class="flex min-w-0 flex-col gap-1.5">
            <div class="flex flex-wrap items-center gap-2 text-p-base-medium text-ink-gray-7">
              <span class="truncate">{{ rule.rule_name }}</span>
              <Badge :label="hoursText(rule)" theme="gray" />
              <Badge v-if="rule.only_assigned" :label="__('Assigned leads only')" theme="blue" />
            </div>
            <div class="flex flex-wrap gap-1">
              <Badge v-for="s in rule.statuses" :key="s" :label="s" variant="outline" theme="gray" />
            </div>
            <div class="text-p-sm text-ink-gray-5">{{ levelsText(rule) }}</div>
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <Switch :modelValue="Boolean(rule.enabled)" size="sm" @update:modelValue="(v) => setEnabled(rule, v)" />
            <Button variant="ghost" icon="edit-2" @click="openForm(rule)" />
            <Button variant="ghost" icon="trash-2" @click="deleteRule(rule)" />
          </div>
        </div>
      </template>
      <div v-if="rules.length" class="mt-4 flex items-center gap-2 px-2">
        <Button :label="__('Run check now')" :loading="running" @click="runNow" />
        <span class="text-p-sm text-ink-gray-5">{{ runResult || __('The check runs automatically every 5 minutes.') }}</span>
      </div>
    </div>

    <!-- idle now -->
    <div v-else-if="tab === 'idle'" class="flex-1 overflow-y-auto px-2">
      <div class="mb-3 max-w-xs">
        <FormControl v-model="idleRule" type="select" :options="ruleFilterOptions" />
      </div>
      <ErrorMessage :message="idle.error" />
      <div v-if="idle.loading && !idle.rows.length" class="py-8 text-center text-ink-gray-5">{{ __('Loading...') }}</div>
      <div v-else-if="!idle.rows.length" class="py-8 text-center text-p-base text-ink-gray-5">{{ __('No idle leads right now') }}</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[560px] text-p-sm">
          <thead class="text-left text-ink-gray-5">
            <tr>
              <th class="py-1.5 pr-3 font-normal">{{ __('Lead') }}</th>
              <th class="py-1.5 pr-3 font-normal">{{ __('Status') }}</th>
              <th class="py-1.5 pr-3 font-normal">{{ __('Owner') }}</th>
              <th class="py-1.5 pr-3 font-normal">{{ __('Idle') }}</th>
              <th class="py-1.5 pr-3 font-normal">{{ __('Rule') }}</th>
              <th class="py-1.5 font-normal">{{ __('Level') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in idle.rows" :key="r.name + r.rule" class="border-t border-outline-gray-1">
              <td class="py-2 pr-3"><a :href="leadHref(r.name)" class="font-medium text-ink-gray-9 hover:underline" @click.prevent="openLead(r.name)">{{ r.lead_name || r.name }}</a></td>
              <td class="py-2 pr-3">{{ r.status }}</td>
              <td class="py-2 pr-3">{{ r.owner_name || r.lead_owner || '-' }}</td>
              <td class="py-2 pr-3">{{ dur(r.idle_minutes) }}</td>
              <td class="py-2 pr-3">{{ r.rule }}</td>
              <td class="py-2">{{ r.level ? dur(r.level) : '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="idle.hasMore" class="mt-3"><Button :label="__('Load more')" :loading="idle.loading" @click="idle.more()" /></div>
    </div>

    <!-- history -->
    <div v-else class="flex-1 overflow-y-auto px-2">
      <div class="mb-3 max-w-xs">
        <FormControl v-model="alertRule" type="select" :options="ruleFilterOptions" />
      </div>
      <ErrorMessage :message="alerts.error" />
      <div v-if="alerts.loading && !alerts.rows.length" class="py-8 text-center text-ink-gray-5">{{ __('Loading...') }}</div>
      <div v-else-if="!alerts.rows.length" class="py-8 text-center text-p-base text-ink-gray-5">{{ __('No alerts sent yet') }}</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[560px] text-p-sm">
          <thead class="text-left text-ink-gray-5">
            <tr>
              <th class="py-1.5 pr-3 font-normal">{{ __('When') }}</th>
              <th class="py-1.5 pr-3 font-normal">{{ __('Lead') }}</th>
              <th class="py-1.5 pr-3 font-normal">{{ __('Rule') }}</th>
              <th class="py-1.5 pr-3 font-normal">{{ __('Level') }}</th>
              <th class="py-1.5 font-normal">{{ __('Sent to') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in alerts.rows" :key="a.name" class="border-t border-outline-gray-1">
              <td class="whitespace-nowrap py-2 pr-3">{{ fmtDateTime(a.creation) }}</td>
              <td class="py-2 pr-3"><a :href="leadHref(a.lead)" class="font-medium text-ink-gray-9 hover:underline" @click.prevent="openLead(a.lead)">{{ a.lead_name || a.lead }}</a></td>
              <td class="py-2 pr-3">{{ a.rule }}</td>
              <td class="py-2 pr-3">{{ dur(a.level) }}</td>
              <td class="py-2">{{ sentTo(a.sent_to) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="alerts.hasMore" class="mt-3"><Button :label="__('Load more')" :loading="alerts.loading" @click="alerts.more()" /></div>
    </div>

    <Dialog v-model:open="showForm" :title="form.name ? __('Edit Idle Lead Rule') : __('New Idle Lead Rule')" :size="'3xl'">
      <template #default>
        <div class="flex max-h-[65vh] flex-col gap-5 overflow-y-auto pr-1">
          <FormControl v-model="form.rule_name" type="text" :label="__('Rule Name')" :placeholder="__('New leads, first-day follow-up')" />

          <div class="flex flex-col gap-2">
            <div class="text-p-base-medium text-ink-gray-8">{{ __('Watch leads in these statuses') }}</div>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="s in statusList"
                :key="s.name"
                type="button"
                class="rounded-full border px-2.5 py-1 text-p-sm transition"
                :class="form.statuses.includes(s.name) ? 'border-ink-gray-9 bg-surface-gray-7 text-ink-white' : 'border-outline-gray-2 bg-surface-white text-ink-gray-7 hover:bg-surface-gray-2'"
                @click="toggleStatus(s.name)"
              >
                {{ s.name }}
              </button>
            </div>
          </div>

          <div class="flex flex-col gap-2">
            <div class="text-p-base-medium text-ink-gray-8">{{ __('Working hours') }}</div>
            <p class="text-p-sm text-ink-gray-5">{{ __('Idle time counts only inside these hours and on the selected days. Time outside them is skipped.') }}</p>
            <div class="grid grid-cols-2 gap-3 sm:max-w-sm">
              <label class="flex flex-col gap-1.5 text-xs text-ink-gray-5">{{ __('Start') }}<input v-model="form.work_start" type="time" class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3" /></label>
              <label class="flex flex-col gap-1.5 text-xs text-ink-gray-5">{{ __('End') }}<input v-model="form.work_end" type="time" class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3" /></label>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="dd in days"
                :key="dd.key"
                type="button"
                class="h-8 w-12 rounded border text-p-sm transition"
                :class="form[dd.key] ? 'border-ink-gray-9 bg-surface-gray-7 text-ink-white' : 'border-outline-gray-2 bg-surface-white text-ink-gray-6 hover:bg-surface-gray-2'"
                @click="form[dd.key] = form[dd.key] ? 0 : 1"
              >
                {{ __(dd.label) }}
              </button>
            </div>
          </div>

          <label class="flex items-center gap-2 text-p-base text-ink-gray-8">
            <Switch v-model="form.only_assigned" size="sm" />
            {{ __('Only leads that have an owner') }}
          </label>

          <div class="flex flex-col gap-2">
            <div class="text-p-base-medium text-ink-gray-8">{{ __('Alert levels') }}</div>
            <p class="text-p-sm text-ink-gray-5">{{ __('Each level fires once per idle period, when the lead has been idle that many working minutes. New activity starts a new period.') }}</p>
            <div v-for="(lv, idx) in form.levels" :key="idx" class="flex flex-col gap-2 rounded-lg border border-outline-gray-2 p-3">
              <div class="grid grid-cols-1 gap-2 sm:grid-cols-[7rem_1fr_1fr]">
                <FormControl v-model="lv.idle_minutes" type="number" :label="__('Idle minutes')" />
                <FormControl v-model="lv.notify_user" type="select" :label="__('Also notify user')" :options="userOptions" />
                <FormControl v-model="lv.notify_role" type="select" :label="__('Also notify role')" :options="roleOptions" />
              </div>
              <FormControl v-model="lv.message" type="text" :label="__('Message (optional)')" />
              <div class="flex items-center justify-between">
                <label class="flex items-center gap-2 text-p-sm text-ink-gray-7">
                  <Switch v-model="lv.notify_owner" size="sm" />
                  {{ __('Notify lead owner') }}
                </label>
                <Button variant="ghost" theme="red" icon="trash-2" :disabled="form.levels.length < 2" @click="form.levels.splice(idx, 1)" />
              </div>
            </div>
            <div><Button :label="__('Add level')" iconLeft="plus" @click="addLevel" /></div>
          </div>

          <div class="flex flex-col gap-2">
            <div class="flex items-center gap-2">
              <Button :label="__('Preview')" :loading="previewing" @click="runPreview" />
              <span class="text-p-sm text-ink-gray-5">{{ __('Lists leads that would be alerted right now. Nothing is sent.') }}</span>
            </div>
            <div v-if="preview" class="rounded-lg bg-surface-gray-1 p-3 text-p-sm">
              <div class="mb-1 font-medium text-ink-gray-8">{{ __('{0} leads would be alerted now', [preview.idle_now]) }}</div>
              <div v-for="l in preview.leads" :key="l.name" class="flex flex-wrap justify-between gap-x-3 py-0.5 text-ink-gray-7">
                <span class="truncate">{{ l.lead_name || l.name }} <span class="text-ink-gray-5">· {{ l.status }}</span></span>
                <span class="text-ink-gray-5">{{ l.owner_name || __('No owner') }} · {{ dur(l.idle_minutes) }}</span>
              </div>
              <div v-if="preview.idle_now > preview.leads.length" class="pt-1 text-ink-gray-5">{{ __('Showing the first {0}', [preview.leads.length]) }}</div>
            </div>
          </div>

          <ErrorMessage :message="formError" />
        </div>
      </template>
      <template #actions>
        <Button class="w-full" variant="solid" :label="__('Save')" :loading="saving" @click="submitForm" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import '@/components/ABM/PersonInput.vue'
import { errorText as errText, fmtDateTime } from '@/components/ABM/visits.js'
import router from '@/router'
import { Badge, Button, Dialog, ErrorMessage, FormControl, Switch, call, createResource, toast } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'

const tabs = [
  { key: 'rules', label: 'Rules' },
  { key: 'idle', label: 'Idle leads now' },
  { key: 'alerts', label: 'Alert history' },
]
const tab = ref('rules')
const days = [
  { key: 'mon', label: 'Mon' }, { key: 'tue', label: 'Tue' }, { key: 'wed', label: 'Wed' },
  { key: 'thu', label: 'Thu' }, { key: 'fri', label: 'Fri' }, { key: 'sat', label: 'Sat' }, { key: 'sun', label: 'Sun' },
]

const setup = createResource({ url: 'abm_crm.api.idle_alerts.get_setup', auto: true })
const rules = computed(() => setup.data?.rules || [])
const statusList = computed(() => setup.data?.statuses || [])
const userOptions = computed(() => [
  { label: __('None'), value: '' },
  ...(setup.data?.users || []).map((u) => ({ label: u.full_name ? `${u.full_name} (${u.name})` : u.name, value: u.name })),
])
const roleOptions = computed(() => [{ label: __('None'), value: '' }, ...(setup.data?.roles || []).map((r) => ({ label: r, value: r }))])
const ruleFilterOptions = computed(() => [{ label: __('All rules'), value: '' }, ...rules.value.map((r) => ({ label: r.rule_name, value: r.name }))])

const dur = (m) => {
  m = Math.round(Number(m) || 0)
  if (m < 60) return __('{0} min', [m])
  const h = Math.floor(m / 60)
  return m % 60 ? `${h} h ${m % 60} min` : `${h} h`
}
const trimTime = (t) => (t ? String(t).slice(0, 5) : '')
const hoursText = (r) => {
  const on = days.filter((x) => r[x.key]).map((x) => __(x.label))
  return `${trimTime(r.work_start)}-${trimTime(r.work_end)} · ${on.length === 7 ? __('every day') : on.join(' ')}`
}
const levelsText = (r) =>
  (r.levels || [])
    .map((l) => {
      const who = [l.notify_owner ? __('owner') : '', l.notify_user, l.notify_role].filter(Boolean).join(', ')
      return `${dur(l.idle_minutes)}: ${who || __('nobody')}`
    })
    .join(' · ')
const sentTo = (v) => (Array.isArray(v) ? v : String(v || '').split(/[\n,]+/)).map((s) => s.trim()).filter(Boolean).join(', ')

const leadHref = (name) => `/crm/leads/${name}`
function openLead(name) {
  // the settings dialog closes with the route change
  router.push({ name: 'Lead', params: { leadId: name } })
}

// rules
async function setEnabled(rule, value) {
  try {
    await call('abm_crm.api.idle_alerts.set_rule_enabled', { name: rule.name, enabled: value ? 1 : 0 })
  } catch (e) {
    toast.error(errText(e, __('Could not update the rule')))
  }
  setup.reload()
}
async function deleteRule(rule) {
  if (!window.confirm(__('Delete idle lead rule {0}?', [rule.rule_name]))) return
  try {
    await call('abm_crm.api.idle_alerts.delete_rule', { name: rule.name })
    toast.success(__('Rule deleted'))
  } catch (e) {
    toast.error(errText(e, __('Could not delete the rule')))
  }
  setup.reload()
}
const running = ref(false)
const runResult = ref('')
async function runNow() {
  running.value = true
  try {
    const r = await call('abm_crm.api.idle_alerts.run_now')
    runResult.value = __('Check done: {0} alerts sent', [r.alerts])
  } catch (e) {
    runResult.value = errText(e, __('Could not run the check'))
  } finally {
    running.value = false
  }
}

// form
const showForm = ref(false)
const saving = ref(false)
const formError = ref('')
const previewing = ref(false)
const preview = ref(null)
const form = ref({ statuses: [], levels: [] })

const newLevel = (mins = 60) => ({ idle_minutes: mins, notify_owner: 1, notify_user: '', notify_role: '', message: '' })
const addLevel = () => {
  const last = form.value.levels.at(-1)
  form.value.levels.push(newLevel(last ? Number(last.idle_minutes) * 2 || 120 : 60))
}
const toggleStatus = (s) => {
  const i = form.value.statuses.indexOf(s)
  i >= 0 ? form.value.statuses.splice(i, 1) : form.value.statuses.push(s)
}

function openForm(rule) {
  formError.value = ''
  preview.value = null
  form.value = rule
    ? {
        name: rule.name,
        rule_name: rule.rule_name,
        enabled: rule.enabled ? 1 : 0,
        statuses: (rule.statuses || []).map((s) => s.status || s),
        work_start: trimTime(rule.work_start),
        work_end: trimTime(rule.work_end),
        only_assigned: Boolean(rule.only_assigned),
        ...Object.fromEntries(days.map((x) => [x.key, rule[x.key] ? 1 : 0])),
        levels: (rule.levels || []).map((l) => ({
          idle_minutes: l.idle_minutes,
          notify_owner: Boolean(l.notify_owner),
          notify_user: l.notify_user || '',
          notify_role: l.notify_role || '',
          message: l.message || '',
        })),
      }
    : {
        rule_name: '',
        enabled: 1,
        statuses: [],
        work_start: '10:30',
        work_end: '19:30',
        only_assigned: true,
        ...Object.fromEntries(days.map((x) => [x.key, x.key === 'sun' ? 0 : 1])),
        levels: [newLevel(60)],
      }
  showForm.value = true
}

function payload() {
  const f = form.value
  return {
    ...(f.name ? { name: f.name } : {}),
    rule_name: f.rule_name.trim(),
    enabled: f.enabled ? 1 : 0,
    statuses: [...f.statuses],
    work_start: f.work_start.length === 5 ? f.work_start + ':00' : f.work_start,
    work_end: f.work_end.length === 5 ? f.work_end + ':00' : f.work_end,
    only_assigned: f.only_assigned ? 1 : 0,
    ...Object.fromEntries(days.map((x) => [x.key, f[x.key] ? 1 : 0])),
    levels: f.levels.map((l) => ({
      idle_minutes: Number(l.idle_minutes) || 0,
      notify_owner: l.notify_owner ? 1 : 0,
      notify_user: l.notify_user || null,
      notify_role: l.notify_role || null,
      message: l.message || '',
    })),
  }
}

function validate() {
  const f = form.value
  if (!f.rule_name?.trim()) return __('Rule name is required')
  if (!f.statuses.length) return __('Pick at least one status')
  if (!f.work_start || !f.work_end || f.work_start >= f.work_end) return __('Working hours must start before they end')
  if (!days.some((x) => f[x.key])) return __('Pick at least one working day')
  if (!f.levels.length || f.levels.some((l) => !(Number(l.idle_minutes) > 0))) return __('Every level needs idle minutes above 0')
  if (f.levels.some((l) => !l.notify_owner && !l.notify_user && !l.notify_role)) return __('Every level must notify someone')
  return ''
}

async function submitForm() {
  formError.value = validate()
  if (formError.value) return
  saving.value = true
  try {
    await call('abm_crm.api.idle_alerts.save_rule', { rule: payload() })
    toast.success(__('Rule saved'))
    showForm.value = false
    setup.reload()
  } catch (e) {
    formError.value = errText(e, __('Could not save the rule'))
  } finally {
    saving.value = false
  }
}

async function runPreview() {
  formError.value = validate()
  if (formError.value) return
  previewing.value = true
  try {
    preview.value = await call('abm_crm.api.idle_alerts.preview_rule', { rule: payload() })
  } catch (e) {
    formError.value = errText(e, __('Could not preview'))
  } finally {
    previewing.value = false
  }
}

// paged lists
function usePaged(method, extra) {
  const s = reactive({ rows: [], hasMore: false, loading: false, error: '' })
  let seq = 0
  async function load(append = false) {
    const my = ++seq
    s.loading = true
    s.error = ''
    try {
      const res = await call(method, { ...extra(), start: append ? s.rows.length : 0, page_length: 20 })
      if (my !== seq) return
      s.rows = append ? [...s.rows, ...res.data] : res.data
      s.hasMore = !!res.has_more
    } catch (e) {
      s.error = errText(e, __('Could not load'))
    } finally {
      if (my === seq) s.loading = false
    }
  }
  s.reload = () => load(false)
  s.more = () => load(true)
  return s
}
const idleRule = ref('')
const alertRule = ref('')
const idle = usePaged('abm_crm.api.idle_alerts.list_idle_leads', () => ({ rule: idleRule.value || undefined }))
const alerts = usePaged('abm_crm.api.idle_alerts.list_alerts', () => ({ rule: alertRule.value || undefined }))
watch(tab, (t) => (t === 'idle' ? idle.reload() : t === 'alerts' ? alerts.reload() : null))
watch(idleRule, () => idle.reload())
watch(alertRule, () => alerts.reload())
function reloadTab() {
  if (tab.value === 'idle') idle.reload()
  else alerts.reload()
}
</script>
