// abm_crm: shared helpers for site visits. API: abm_crm.api.visits (docs/mobile-api.md, "Site visits").
import { call, createResource, toast } from 'frappe-ui'
import { computed } from 'vue'
import { tagChipClass, tagDotClass } from './tags.js'

export const DEFAULT_STATUSES = [
  { name: 'Pending', color: 'gray' },
  { name: 'Scheduled', color: 'blue' },
  { name: 'Visited', color: 'green' },
  { name: 'Postponed', color: 'orange' },
  { name: 'Cancelled', color: 'red' },
  { name: 'No Show', color: 'pink' },
]
export const NEEDS_DATE = ['Scheduled', 'Postponed']

const options = createResource({
  url: 'abm_crm.api.visits.get_visit_options',
  cache: 'abm_visit_options',
})
let requested = false

export function useVisitOptions() {
  if (!requested) {
    requested = true
    options.fetch()
  }
  const statuses = computed(() => options.data?.statuses || DEFAULT_STATUSES)
  const types = computed(() => options.data?.types || ['Site Visit', 'Walk-in', 'Office Meeting'])
  const outcomes = computed(() => options.data?.outcomes || ['', 'Interested', 'Needs Follow-up', 'Not Interested', 'Booked'])
  const projects = computed(() => options.data?.projects || [])
  const users = computed(() => options.data?.users || [])
  const colorOf = (status) => statuses.value.find((s) => s.name === status)?.color || 'gray'
  return { options, statuses, types, outcomes, projects, users, colorOf }
}

export const chipClass = (color) => tagChipClass(color)
export const dotClass = (color) => tagDotClass(color)

const pad = (n) => String(n).padStart(2, '0')
// Frappe datetimes are "YYYY-MM-DD HH:mm:ss" in the site timezone
export function parseDt(value) {
  if (!value) return null
  const d = new Date(String(value).replace(' ', 'T'))
  return isNaN(d) ? null : d
}
export function fmtDateTime(value) {
  const d = parseDt(value)
  if (!d) return ''
  return d.toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}
export function fmtDate(value) {
  const d = parseDt(value)
  if (!d) return ''
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}
export const toDateInput = (value) => {
  const d = parseDt(value)
  return d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : ''
}
export const toTimeInput = (value) => {
  const d = parseDt(value)
  return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : ''
}
export const joinDateTime = (date, time) => (date ? `${date} ${time || '10:00'}:00` : '')
export const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

export const ROLES = [
  { key: 'closing_manager', label: 'Closing manager' },
  { key: 'attended_by', label: 'Attended by' },
  { key: 'site_visit_assistant', label: 'Site visit assistant' },
]

// "who" shown on a card: [{label, name}]
export const people = (v) =>
  ROLES.map((r) => ({ label: r.label, name: v[r.key + '_name'] || v[r.key] })).filter((p) => p.name)

export function refRoute(v) {
  return v.reference_doctype === 'CRM Deal'
    ? { name: 'Deal', params: { dealId: v.reference_docname } }
    : { name: 'Lead', params: { leadId: v.reference_docname } }
}

export const errorText = (err, fallback) =>
  err?.messages?.[0]?.replace?.(/<[^>]+>/g, '') || err?.message || fallback

// one-click state changes
export async function updateVisit(name, data) {
  try {
    const res = await call('abm_crm.api.visits.update_visit', { name, data })
    return res
  } catch (err) {
    toast.error(errorText(err, __('Could not update the visit')))
    throw err
  }
}

export async function deleteVisit(visit) {
  if (!window.confirm(__('Delete this visit?'))) return false
  try {
    await call('abm_crm.api.visits.delete_visit', { name: visit.name })
    toast.success(__('Visit deleted'))
    return true
  } catch (err) {
    toast.error(errorText(err, __('Could not delete the visit')))
    return false
  }
}

// actions offered per status
export function actionsFor(visit) {
  const s = visit.status
  const open = ['Pending', 'Scheduled', 'Postponed'].includes(s)
  return {
    visited: open,
    postpone: open,
    cancel: open,
    noShow: s === 'Scheduled' || s === 'Pending',
  }
}
