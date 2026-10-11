<template>
  <!-- abm_crm: pick a system user or type any name -->
  <div ref="root" class="relative">
    <label class="mb-1.5 block text-xs text-ink-gray-5">{{ label }}</label>
    <div class="relative">
      <input
        v-model="text"
        type="text"
        class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3 pr-7"
        :placeholder="__('Pick a user or type a name')"
        autocomplete="off"
        @focus="show = true"
        @input="onType"
        @keydown.esc="show = false"
      />
      <button
        v-if="text"
        type="button"
        class="absolute right-1.5 top-1.5 text-ink-gray-4 hover:text-ink-gray-7"
        :title="__('Clear')"
        @click="clear"
      >
        <span class="lucide-x size-4 block" />
      </button>
    </div>
    <div
      v-if="show && matches.length"
      class="absolute z-50 mt-1 max-h-48 w-full min-w-[14rem] overflow-y-auto rounded-lg border border-outline-gray-2 bg-white p-1 shadow-xl"
    >
      <button
        v-for="u in matches"
        :key="u.name"
        type="button"
        class="flex w-full flex-col rounded px-2 py-1 text-left text-base text-ink-gray-8 hover:bg-surface-gray-2"
        @mousedown.prevent="pick(u)"
      >
        <span class="truncate">{{ u.full_name || u.name }}</span>
        <span class="truncate text-xs text-ink-gray-5">{{ u.name }}</span>
      </button>
    </div>
    <div v-if="user" class="mt-1 text-xs text-ink-gray-5">{{ __('CRM user') }}: {{ user }}</div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  label: String,
  users: { type: Array, default: () => [] },
})
const name = defineModel('name', { type: String, default: '' })
const user = defineModel('user', { type: String, default: '' })

const text = ref(name.value)
const show = ref(false)
const root = ref(null)

watch(name, (v) => {
  if (v !== text.value) text.value = v
})

const matches = computed(() => {
  const q = (text.value || '').toLowerCase().trim()
  return props.users
    .filter((u) => !q || (u.full_name || '').toLowerCase().includes(q) || u.name.toLowerCase().includes(q))
    .slice(0, 30)
})

function onType() {
  // typing a name detaches the system user
  name.value = text.value
  user.value = ''
  show.value = true
}
function pick(u) {
  text.value = u.full_name || u.name
  name.value = text.value
  user.value = u.name
  show.value = false
}
function clear() {
  text.value = ''
  name.value = ''
  user.value = ''
}
const outside = (e) => {
  if (root.value && !root.value.contains(e.target)) show.value = false
}
onMounted(() => document.addEventListener('mousedown', outside))
onBeforeUnmount(() => document.removeEventListener('mousedown', outside))
</script>

