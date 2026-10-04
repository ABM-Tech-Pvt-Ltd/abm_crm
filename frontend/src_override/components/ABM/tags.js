// abm_crm: shared helpers for record tags (Frappe's Tag doctype + `_user_tags`).
// API: abm_crm.api.tags (see docs/mobile-api.md, "Tags").
import { createResource } from 'frappe-ui'
import { computed } from 'vue'

export const TAG_CATEGORIES = ['Builder', 'Project', 'Location', 'Budget', 'Other']

export const TAG_COLORS = [
  'gray',
  'blue',
  'green',
  'red',
  'pink',
  'orange',
  'amber',
  'yellow',
  'cyan',
  'teal',
  'violet',
  'purple',
]

// Full class names (not built from strings) so Tailwind generates them.
const CHIP = {
  gray: 'bg-gray-100 text-gray-700 border-gray-200',
  blue: 'bg-blue-50 text-blue-700 border-blue-200',
  green: 'bg-green-50 text-green-700 border-green-200',
  red: 'bg-red-50 text-red-700 border-red-200',
  pink: 'bg-pink-50 text-pink-700 border-pink-200',
  orange: 'bg-orange-50 text-orange-700 border-orange-200',
  amber: 'bg-amber-50 text-amber-700 border-amber-200',
  yellow: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  cyan: 'bg-cyan-50 text-cyan-700 border-cyan-200',
  teal: 'bg-teal-50 text-teal-700 border-teal-200',
  violet: 'bg-violet-50 text-violet-700 border-violet-200',
  purple: 'bg-purple-50 text-purple-700 border-purple-200',
}

const DOT = {
  gray: 'bg-gray-500',
  blue: 'bg-blue-500',
  green: 'bg-green-500',
  red: 'bg-red-500',
  pink: 'bg-pink-500',
  orange: 'bg-orange-500',
  amber: 'bg-amber-500',
  yellow: 'bg-yellow-500',
  cyan: 'bg-cyan-500',
  teal: 'bg-teal-500',
  violet: 'bg-violet-500',
  purple: 'bg-purple-500',
}

// strong variant, used for the "Talk as" builder highlight
const SOLID = {
  gray: 'bg-gray-700 text-white',
  blue: 'bg-blue-600 text-white',
  green: 'bg-green-600 text-white',
  red: 'bg-red-600 text-white',
  pink: 'bg-pink-600 text-white',
  orange: 'bg-orange-600 text-white',
  amber: 'bg-amber-600 text-white',
  yellow: 'bg-yellow-600 text-white',
  cyan: 'bg-cyan-600 text-white',
  teal: 'bg-teal-600 text-white',
  violet: 'bg-violet-600 text-white',
  purple: 'bg-purple-600 text-white',
}

export const tagChipClass = (color) => CHIP[color] || CHIP.gray
export const tagDotClass = (color) => DOT[color] || DOT.gray
export const tagSolidClass = (color) => SOLID[color] || SOLID.gray

// `_user_tags` is stored as ",Lodha,Hot" by Frappe
export function parseUserTags(value) {
  if (!value || typeof value !== 'string') return []
  return [...new Set(value.split(',').map((t) => t.trim()).filter(Boolean))]
}

// every Tag with its category/color/count; one shared, cached resource
const allTags = createResource({
  url: 'abm_crm.api.tags.get_tags',
  cache: 'abm_crm_tags',
})

let requested = false

export function useTags() {
  // cached data shows instantly; refresh once per page load
  if (!requested) {
    requested = true
    allTags.fetch()
  }
  const byName = computed(() => {
    const map = {}
    for (const tag of allTags.data || []) map[tag.name] = tag
    return map
  })
  const tagMeta = (name) =>
    byName.value[name] || { name, category: null, color: null }
  return { allTags, byName, tagMeta }
}
