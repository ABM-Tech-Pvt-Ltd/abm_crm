<template>
  <!-- abm_crm: Site Visits dashboard and list (route /crm/site-visits) -->
  <div class="flex h-full flex-col overflow-hidden">
    <LayoutHeader>
      <template #left-header>
        <div class="px-0.5 py-1 text-lg-medium text-ink-gray-7">{{ __('Site Visits') }}</div>
      </template>
      <template #right-header>
        <Button :label="__('Refresh')" iconLeft="refresh-cw" @click="refresh" />
      </template>
    </LayoutHeader>

    <div class="flex-1 overflow-y-auto">
      <div class="mx-auto flex max-w-[1400px] flex-col gap-6 px-3 py-4 sm:px-6">
        <!-- filters -->
        <div class="flex flex-col gap-2">
          <div class="flex flex-wrap items-center gap-2">
            <div class="inline-flex overflow-hidden rounded border border-outline-gray-2">
              <button
                v-for="p in presets"
                :key="p.key"
                class="px-3 py-1 text-sm"
                :class="preset === p.key ? 'bg-surface-gray-7 text-ink-white' : 'bg-surface-white text-ink-gray-7 hover:bg-surface-gray-2'"
                @click="setPreset(p.key)"
              >
                {{ __(p.label) }}
              </button>
            </div>
            <template v-if="preset === 'custom'">
              <input v-model="dateFrom" type="date" class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3 !w-36" />
              <span class="text-ink-gray-5">-</span>
              <input v-model="dateTo" type="date" class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3 !w-36" />
            </template>
            <span class="text-sm text-ink-gray-5">{{ rangeLabel }}</span>
          </div>
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <FormControl v-model="status" type="select" :options="statusOpts" />
            <FormControl v-model="visitType" type="select" :options="typeOpts" />
            <FormControl v-model="user" type="select" :options="userOpts" />
            <input v-model="project" list="abm-sv-projects" class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3 !h-7" :placeholder="__('Project')" />
            <datalist id="abm-sv-projects">
              <option v-for="p in projects" :key="p" :value="p" />
            </datalist>
            <FormControl v-model="search" class="col-span-2" type="text" :placeholder="__('Search project, name, lead, phone')" />
          </div>
        </div>

        <!-- dashboard -->
        <section class="flex flex-col gap-4">
          <div v-if="dash.loading && !dash.data" class="py-10 text-center text-ink-gray-5">{{ __('Loading...') }}</div>
          <template v-if="d">
            <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-10">
              <div
                v-for="k in kpis"
                :key="k.label"
                class="rounded-lg border border-outline-gray-1 bg-surface-cards p-3"
              >
                <div class="truncate text-xs text-ink-gray-5">{{ __(k.label) }}</div>
                <div class="mt-1 text-2xl font-semibold" :class="k.cls || 'text-ink-gray-9'">{{ k.value }}</div>
              </div>
            </div>

            <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <!-- status breakdown -->
              <div class="rounded-lg border border-outline-gray-1 bg-surface-cards p-4">
                <div class="mb-3 text-p-base-medium text-ink-gray-8">{{ __('By status') }}</div>
                <div class="flex h-3 overflow-hidden rounded-full bg-surface-gray-2">
                  <div
                    v-for="s in d.by_status"
                    :key="s.status"
                    :class="dotClass(s.color)"
                    :style="{ width: pct(s.count, d.totals.total) + '%' }"
                    :title="`${s.status}: ${s.count}`"
                  />
                </div>
                <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
                  <span v-for="s in d.by_status" :key="s.status" class="flex items-center gap-1.5 text-sm text-ink-gray-7">
                    <span class="size-2 rounded-full" :class="dotClass(s.color)" />
                    {{ __(s.status) }}: <b class="text-ink-gray-9">{{ s.count }}</b>
                  </span>
                </div>
                <div v-if="d.by_type?.length" class="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-gray-6">
                  <span v-for="t in d.by_type" :key="t.visit_type">{{ __(t.visit_type) }}: <b class="text-ink-gray-9">{{ t.count }}</b></span>
                </div>
              </div>

              <!-- daily chart -->
              <div class="rounded-lg border border-outline-gray-1 bg-surface-cards p-4">
                <div class="mb-3 flex items-center justify-between">
                  <span class="text-p-base-medium text-ink-gray-8">{{ __('Scheduled vs visited per day') }}</span>
                  <span class="flex gap-3 text-xs text-ink-gray-6">
                    <span class="flex items-center gap-1"><span class="size-2 rounded-sm bg-blue-500" />{{ __('Scheduled') }}</span>
                    <span class="flex items-center gap-1"><span class="size-2 rounded-sm bg-green-500" />{{ __('Visited') }}</span>
                  </span>
                </div>
                <div v-if="!d.by_day?.length" class="py-8 text-center text-sm text-ink-gray-5">{{ __('No visits in this range') }}</div>
                <div v-else class="overflow-x-auto">
                  <div class="flex h-40 items-end gap-1" :style="{ minWidth: d.by_day.length * 22 + 'px' }">
                    <div
                      v-for="day in d.by_day"
                      :key="day.date"
                      class="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1"
                      :title="`${day.date}: ${day.scheduled} scheduled, ${day.visited} visited`"
                    >
                      <div class="flex h-full w-full items-end justify-center gap-px">
                        <div class="w-1/2 max-w-3 rounded-t bg-blue-500" :style="{ height: bar(day.scheduled) }" />
                        <div class="w-1/2 max-w-3 rounded-t bg-green-500" :style="{ height: bar(day.visited) }" />
                      </div>
                      <span class="text-[10px] leading-none text-ink-gray-5">{{ day.date.slice(8) }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- people and projects -->
            <div class="grid grid-cols-1 gap-4">
              <div class="rounded-lg border border-outline-gray-1 bg-surface-cards">
                <div class="px-4 pt-4 text-p-base-medium text-ink-gray-8">{{ __('By person') }}</div>
                <div class="overflow-x-auto p-2">
                  <table class="w-full min-w-[640px] text-sm">
                    <thead class="text-xs text-ink-gray-5">
                      <tr class="text-right">
                        <th class="px-2 py-1.5 text-left font-normal">{{ __('Person') }}</th>
                        <th v-for="c in userCols" :key="c.key" class="px-2 py-1.5 font-normal">{{ __(c.label) }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="u in d.by_user" :key="u.user || u.name" class="border-t border-outline-gray-1 text-right text-ink-gray-8">
                        <td class="whitespace-nowrap px-2 py-1.5 text-left">
                          <button class="text-left hover:underline" @click="filterUser(u)">{{ u.name }}</button>
                          <span v-if="!u.user" class="ml-1 text-xs text-ink-gray-4">{{ __('(name only)') }}</span>
                        </td>
                        <td v-for="c in userCols" :key="c.key" class="px-2 py-1.5" :class="c.key === 'total' && 'font-medium'">{{ u[c.key] }}</td>
                      </tr>
                      <tr v-if="!d.by_user?.length"><td :colspan="userCols.length + 1" class="px-2 py-6 text-center text-ink-gray-5">{{ __('No data') }}</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div class="rounded-lg border border-outline-gray-1 bg-surface-cards">
                <div class="px-4 pt-4 text-p-base-medium text-ink-gray-8">{{ __('By project') }}</div>
                <div class="overflow-x-auto p-2">
                  <table class="w-full min-w-[320px] text-sm">
                    <thead class="text-xs text-ink-gray-5">
                      <tr class="text-right">
                        <th class="px-2 py-1.5 text-left font-normal">{{ __('Project') }}</th>
                        <th class="px-2 py-1.5 font-normal">{{ __('Total') }}</th>
                        <th class="px-2 py-1.5 font-normal">{{ __('Visited') }}</th>
                        <th class="px-2 py-1.5 font-normal">{{ __('Booked') }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="p in d.by_project" :key="p.project" class="border-t border-outline-gray-1 text-right text-ink-gray-8">
                        <td class="px-2 py-1.5 text-left"><button class="text-left hover:underline" @click="project = p.project">{{ p.project || __('No project') }}</button></td>
                        <td class="px-2 py-1.5 font-medium">{{ p.total }}</td>
                        <td class="px-2 py-1.5">{{ p.visited }}</td>
                        <td class="px-2 py-1.5">{{ p.booked }}</td>
                      </tr>
                      <tr v-if="!d.by_project?.length"><td colspan="4" class="px-2 py-6 text-center text-ink-gray-5">{{ __('No data') }}</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <!-- today / upcoming / overdue -->
            <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div
                v-for="g in groups"
                :key="g.title"
                class="rounded-lg border border-outline-gray-1 bg-surface-cards p-3"
              >
                <div class="mb-2 flex items-center gap-2 text-p-base-medium text-ink-gray-8">
                  {{ __(g.title) }}
                  <span class="rounded-full px-2 text-xs" :class="g.badge">{{ g.rows.length }}</span>
                </div>
                <div v-if="!g.rows.length" class="py-4 text-center text-sm text-ink-gray-5">{{ __('Nothing here') }}</div>
                <router-link
                  v-for="v in g.rows"
                  :key="v.name"
                  :to="refRoute(v)"
                  class="flex flex-col gap-0.5 rounded px-2 py-1.5 hover:bg-surface-gray-2"
                >
                  <div class="flex items-center justify-between gap-2 text-sm">
                    <span class="truncate font-medium text-ink-gray-9">{{ v.reference_title }}</span>
                    <span class="shrink-0 text-xs text-ink-gray-6">{{ fmtDateTime(v.scheduled_on || v.visit_date) }}</span>
                  </div>
                  <div class="truncate text-xs text-ink-gray-5">
                    {{ [v.project, v.closing_manager_name || v.attended_by_name].filter(Boolean).join(' · ') }}
                  </div>
                </router-link>
              </div>
            </div>
          </template>
        </section>

        <!-- list -->
        <section class="flex flex-col gap-3">
          <div class="flex items-center justify-between">
            <h2 class="text-lg font-medium text-ink-gray-8">{{ __('All visits') }}</h2>
            <span class="text-sm text-ink-gray-5">{{ __('{0} shown', [rows.length]) }}</span>
          </div>
          <div v-if="loadingList && !rows.length" class="py-8 text-center text-ink-gray-5">{{ __('Loading...') }}</div>
          <div v-else-if="!rows.length" class="py-10 text-center text-ink-gray-5">{{ __('No visits match these filters') }}</div>
          <div class="grid grid-cols-1 gap-3 2xl:grid-cols-2">
            <VisitCard
              v-for="v in rows"
              :key="v.name"
              :visit="v"
              linkable
              @edit="(x) => dialogs.edit(x)"
              @action="(x, s) => dialogs.action(x, s)"
              @delete="(x) => dialogs.remove(x)"
            />
          </div>
          <div v-if="hasMore" class="flex justify-center">
            <Button :label="__('Load more')" :loading="loadingList" @click="loadMore" />
          </div>
        </section>
      </div>
    </div>
    <VisitDialogs ref="dialogs" @changed="refresh" />
  </div>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import VisitCard from '@/components/ABM/VisitCard.vue'
import VisitDialogs from '@/components/ABM/VisitDialogs.vue'
import '@/components/ABM/PersonInput.vue'
import { dotClass, fmtDateTime, isoDate, refRoute, useVisitOptions } from '@/components/ABM/visits.js'
import { Button, FormControl, call, createResource } from 'frappe-ui'
import { useDebounceFn } from '@vueuse/core'
import { computed, onMounted, ref, watch } from 'vue'

const { statuses, types, projects, users } = useVisitOptions()
const dialogs = ref(null)

const presets = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: 'This week' },
  { key: 'month', label: 'This month' },
  { key: 'custom', label: 'Custom' },
]
const preset = ref('month')
const dateFrom = ref('')
const dateTo = ref('')
const status = ref('')
const visitType = ref('')
const user = ref('')
const project = ref('')
const search = ref('')

function setPreset(key) {
  preset.value = key
  const now = new Date()
  if (key === 'today') {
    dateFrom.value = dateTo.value = isoDate(now)
  } else if (key === 'week') {
    const mon = new Date(now)
    mon.setDate(now.getDate() - ((now.getDay() + 6) % 7))
    const sun = new Date(mon)
    sun.setDate(mon.getDate() + 6)
    dateFrom.value = isoDate(mon)
    dateTo.value = isoDate(sun)
  } else if (key === 'month') {
    dateFrom.value = isoDate(new Date(now.getFullYear(), now.getMonth(), 1))
    dateTo.value = isoDate(new Date(now.getFullYear(), now.getMonth() + 1, 0))
  }
}
setPreset('month')

const rangeLabel = computed(() =>
  dateFrom.value && dateTo.value ? `${dateFrom.value} → ${dateTo.value}` : '',
)

const opt = (label, value) => ({ label, value })
const statusOpts = computed(() => [opt(__('All statuses'), ''), ...statuses.value.map((s) => opt(__(s.name), s.name))])
const typeOpts = computed(() => [opt(__('All types'), ''), ...types.value.map((t) => opt(__(t), t))])
const userOpts = computed(() => [
  opt(__('Anyone'), ''),
  ...users.value.map((u) => opt(u.full_name || u.name, u.name)),
])

// dashboard
const dashParams = () => ({
  date_from: dateFrom.value || undefined,
  date_to: dateTo.value || undefined,
  user: user.value || undefined,
  project: project.value || undefined,
  visit_type: visitType.value || undefined,
})
const dash = createResource({
  url: 'abm_crm.api.visits.visit_dashboard',
  makeParams: dashParams,
})
const d = computed(() => dash.data)

const kpis = computed(() => {
  const t = d.value?.totals
  if (!t) return []
  return [
    { label: 'Total', value: t.total },
    { label: 'Scheduled', value: t.scheduled, cls: 'text-blue-600' },
    { label: 'Visited', value: t.visited, cls: 'text-green-600' },
    { label: 'Postponed', value: t.postponed, cls: 'text-amber-600' },
    { label: 'Cancelled', value: t.cancelled, cls: 'text-red-600' },
    { label: 'Pending', value: t.pending },
    { label: 'Today', value: t.today },
    { label: 'Overdue', value: t.overdue, cls: t.overdue ? 'text-red-600' : '' },
    { label: 'Completion rate', value: Math.round(t.completion_rate || 0) + '%' },
    { label: 'Booked', value: t.booked, cls: 'text-green-600' },
  ]
})
const userCols = [
  { key: 'total', label: 'Total' },
  { key: 'visited', label: 'Visited' },
  { key: 'scheduled', label: 'Scheduled' },
  { key: 'pending', label: 'Pending' },
  { key: 'postponed', label: 'Postponed' },
  { key: 'cancelled', label: 'Cancelled' },
  { key: 'no_show', label: 'No show' },
  { key: 'as_closing_manager', label: 'As closing mgr' },
  { key: 'as_attended_by', label: 'As attended by' },
  { key: 'as_assistant', label: 'As assistant' },
]
const groups = computed(() => [
  { title: 'Today', rows: d.value?.today || [], badge: 'bg-blue-50 text-blue-700' },
  { title: 'Upcoming', rows: d.value?.upcoming || [], badge: 'bg-gray-100 text-gray-700' },
  { title: 'Overdue', rows: d.value?.overdue || [], badge: 'bg-red-50 text-red-700' },
])
const pct = (n, total) => (total ? Math.max((n / total) * 100, n ? 1 : 0) : 0)
const maxDay = computed(() => Math.max(1, ...(d.value?.by_day || []).flatMap((x) => [x.scheduled, x.visited])))
const bar = (n) => (n ? Math.max((n / maxDay.value) * 100, 4) + '%' : '0%')

// list
const rows = ref([])
const hasMore = ref(false)
const loadingList = ref(false)
const PAGE = 20
let seq = 0

async function fetchList(append = false) {
  const my = ++seq
  loadingList.value = true
  try {
    const res = await call('abm_crm.api.visits.list_visits', {
      status: status.value || undefined,
      visit_type: visitType.value || undefined,
      user: user.value || undefined,
      project: project.value || undefined,
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
      search: search.value || undefined,
      start: append ? rows.value.length : 0,
      page_length: PAGE,
    })
    if (my !== seq) return
    rows.value = append ? [...rows.value, ...res.data] : res.data
    hasMore.value = !!res.has_more
  } finally {
    if (my === seq) loadingList.value = false
  }
}
const loadMore = () => fetchList(true)

function refresh() {
  dash.fetch()
  fetchList()
}
const refreshDebounced = useDebounceFn(refresh, 350)
watch([dateFrom, dateTo, status, visitType, user, project, search], refreshDebounced)
onMounted(refresh)

function filterUser(u) {
  if (u.user) user.value = u.user
}
</script>
