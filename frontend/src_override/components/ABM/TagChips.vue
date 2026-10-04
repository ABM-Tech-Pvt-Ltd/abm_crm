<template>
  <!-- abm_crm: read-only tag chips for a list cell (`_user_tags` value) -->
  <div class="flex items-center gap-1 overflow-hidden">
    <span
      v-for="tag in shown"
      :key="tag.name"
      class="inline-flex h-5 shrink-0 items-center gap-1 rounded-full border px-1.5 text-xs"
      :class="[
        tagChipClass(tag.color),
        tag.category == 'Builder' ? 'font-semibold' : '',
      ]"
      :title="tag.category ? `${__(tag.category)}: ${tag.name}` : tag.name"
    >
      <span class="size-1.5 rounded-full" :class="tagDotClass(tag.color)" />
      {{ tag.name }}
    </span>
    <span v-if="extra" class="shrink-0 text-xs text-ink-gray-5">+{{ extra }}</span>
  </div>
</template>

<script setup>
import { parseUserTags, tagChipClass, tagDotClass, useTags } from './tags'
import { computed } from 'vue'

const props = defineProps({
  value: { type: String, default: '' },
  max: { type: Number, default: 3 },
})

const { tagMeta } = useTags()
const all = computed(() =>
  parseUserTags(props.value)
    .map(tagMeta)
    .sort((a, b) => (b.category == 'Builder') - (a.category == 'Builder')),
)
const shown = computed(() => all.value.slice(0, props.max))
const extra = computed(() => Math.max(all.value.length - props.max, 0))
</script>
