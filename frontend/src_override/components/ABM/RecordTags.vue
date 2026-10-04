<template>
  <!-- abm_crm: tags on a lead/deal, with a "Talk as <Builder>" highlight for reps -->
  <div
    class="flex flex-col gap-2"
    :class="variant == 'mobile' ? 'border-b px-3 py-2.5' : 'border-b px-5 py-3'"
  >
    <div
      v-for="builder in builderTags"
      :key="'talk-' + builder.name"
      class="flex items-center gap-2 rounded-lg px-3 py-2"
      :class="tagSolidClass(builder.color || 'blue')"
      data-testid="abm-talk-as"
    >
      <LucideMegaphone class="size-4 shrink-0" />
      <span class="truncate text-base">
        {{ __('Talk as') }}:
        <span class="font-semibold">{{ builder.name }}</span>
      </span>
    </div>

    <div class="flex flex-wrap items-center gap-1.5">
      <span
        v-for="tag in tags"
        :key="tag.name"
        class="group inline-flex h-6 max-w-full items-center gap-1 rounded-full border pl-2 text-sm"
        :class="[tagChipClass(tag.color), canEdit ? 'pr-1' : 'pr-2']"
        :title="tag.category ? `${__(tag.category)}: ${tag.name}` : tag.name"
        data-testid="abm-tag-chip"
      >
        <span class="size-1.5 shrink-0 rounded-full" :class="tagDotClass(tag.color)" />
        <span class="truncate">{{ tag.name }}</span>
        <button
          v-if="canEdit"
          type="button"
          class="flex size-4 shrink-0 items-center justify-center rounded-full opacity-60 hover:bg-black/10 hover:opacity-100"
          :aria-label="__('Remove tag {0}', [tag.name])"
          @click="removeTag(tag.name)"
        >
          <LucideX class="size-3" />
        </button>
      </span>

      <Popover v-if="canEdit" placement="bottom-start" @open="onOpen">
        <template #target="{ togglePopover }">
          <button
            type="button"
            class="inline-flex h-6 items-center gap-1 rounded-full border border-dashed border-outline-gray-2 px-2 text-sm text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8"
            data-testid="abm-add-tag"
            @click="togglePopover()"
          >
            <LucideTag v-if="!tags.length" class="size-3" />
            <LucidePlus v-else class="size-3" />
            {{ tags.length ? __('Tag') : __('Add tag') }}
          </button>
        </template>
        <template #body-main="{ close }">
          <div class="flex w-72 flex-col" @keydown.esc.stop="close()">
            <div class="p-2 pb-1">
              <TextInput
                ref="searchInput"
                v-model="query"
                type="text"
                :placeholder="__('Search or create a tag')"
                data-testid="abm-tag-search"
                @keydown.enter.prevent="onEnter"
              />
            </div>

            <div v-if="!creating" class="max-h-64 overflow-y-auto px-1 pb-1">
              <template v-for="group in groups" :key="group.label">
                <div class="px-2 pb-1 pt-2 text-xs text-ink-gray-5">
                  {{ __(group.label) }}
                </div>
                <button
                  v-for="tag in group.tags"
                  :key="tag.name"
                  type="button"
                  class="flex h-7 w-full items-center gap-2 rounded px-2 text-left text-base text-ink-gray-8 hover:bg-surface-gray-2"
                  @click="toggleTag(tag.name)"
                >
                  <span class="size-2 shrink-0 rounded-full" :class="tagDotClass(tag.color)" />
                  <span class="flex-1 truncate">{{ tag.name }}</span>
                  <LucideCheck v-if="applied.has(tag.name)" class="size-4 text-ink-gray-7" />
                  <span v-else-if="tag.count" class="text-xs text-ink-gray-4">{{ tag.count }}</span>
                </button>
              </template>
              <div
                v-if="!groups.length && !query.trim()"
                class="px-2 py-3 text-center text-sm text-ink-gray-5"
              >
                {{ allTags.loading ? __('Loading...') : __('No tags yet. Type to create one.') }}
              </div>
              <button
                v-if="canCreate"
                type="button"
                class="mt-1 flex h-7 w-full items-center gap-2 rounded px-2 text-left text-base text-ink-gray-8 hover:bg-surface-gray-2"
                data-testid="abm-tag-create"
                @click="startCreate"
              >
                <LucidePlus class="size-4 shrink-0 text-ink-gray-6" />
                <span class="truncate">{{ __('Create "{0}"', [query.trim()]) }}</span>
              </button>
            </div>

            <div v-else class="flex flex-col gap-3 p-2 pt-1">
              <div class="text-sm text-ink-gray-7">
                {{ __('New tag') }}:
                <span
                  class="ml-1 inline-flex h-6 items-center gap-1 rounded-full border px-2 text-sm"
                  :class="tagChipClass(newColor)"
                >
                  <span class="size-1.5 rounded-full" :class="tagDotClass(newColor)" />
                  {{ query.trim() }}
                </span>
              </div>
              <FormControl
                v-model="newCategory"
                type="select"
                :label="__('Category')"
                :options="categoryOptions"
                data-testid="abm-tag-category"
              />
              <div class="flex flex-col gap-1.5">
                <span class="text-xs text-ink-gray-5">{{ __('Color') }}</span>
                <div class="flex flex-wrap gap-1.5">
                  <button
                    v-for="color in TAG_COLORS"
                    :key="color"
                    type="button"
                    class="flex size-6 items-center justify-center rounded-full ring-offset-1"
                    :class="[tagDotClass(color), newColor == color ? 'ring-2 ring-outline-gray-4' : '']"
                    :aria-label="color"
                    :data-color="color"
                    @click="newColor = color"
                  >
                    <LucideCheck v-if="newColor == color" class="size-3.5 text-white" />
                  </button>
                </div>
              </div>
              <div class="flex justify-end gap-2">
                <Button :label="__('Back')" @click="creating = false" />
                <Button
                  variant="solid"
                  :label="__('Create & add')"
                  :loading="busy"
                  data-testid="abm-tag-create-submit"
                  @click="createTag(close)"
                />
              </div>
            </div>
          </div>
        </template>
      </Popover>
    </div>
  </div>
</template>

<script setup>
import LucideMegaphone from '~icons/lucide/megaphone'
import LucideX from '~icons/lucide/x'
import LucideTag from '~icons/lucide/tag'
import LucidePlus from '~icons/lucide/plus'
import LucideCheck from '~icons/lucide/check'
import {
  TAG_CATEGORIES,
  TAG_COLORS,
  tagChipClass,
  tagDotClass,
  tagSolidClass,
  useTags,
} from './tags'
import {
  Button,
  FormControl,
  Popover,
  TextInput,
  call,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
  variant: { type: String, default: 'panel' }, // 'panel' (desktop side panel) | 'mobile'
  canEdit: { type: Boolean, default: true },
})

const { allTags } = useTags()

const docTags = createResource({
  url: 'abm_crm.api.tags.get_doc_tags',
  makeParams: () => ({ doctype: props.doctype, name: props.docname }),
  cache: ['abm_doc_tags', props.doctype, props.docname],
  auto: true,
})
watch(
  () => props.docname,
  () => docTags.reload(),
)

const tags = computed(() => docTags.data || [])
const applied = computed(() => new Set(tags.value.map((t) => t.name)))
const builderTags = computed(() =>
  tags.value.filter((t) => t.category == 'Builder'),
)

const query = ref('')
const creating = ref(false)
const busy = ref(false)
const newCategory = ref('')
const newColor = ref('blue')
const searchInput = ref(null)

const categoryOptions = [
  { label: __('No category'), value: '' },
  ...TAG_CATEGORIES.map((c) => ({ label: __(c), value: c })),
]

const groups = computed(() => {
  const q = query.value.trim().toLowerCase()
  const list = (allTags.data || []).filter(
    (t) => !q || t.name.toLowerCase().includes(q),
  )
  const order = [...TAG_CATEGORIES, '']
  const byCat = {}
  for (const tag of list) {
    const cat = order.includes(tag.category || '') ? tag.category || '' : 'Other'
    ;(byCat[cat] ||= []).push(tag)
  }
  return order
    .filter((cat) => byCat[cat]?.length)
    .map((cat) => ({ label: cat || 'Uncategorized', tags: byCat[cat] }))
})

const canCreate = computed(() => {
  const q = query.value.trim().toLowerCase()
  return q && !(allTags.data || []).some((t) => t.name.toLowerCase() == q)
})

function onOpen() {
  query.value = ''
  creating.value = false
  allTags.reload()
  nextTick(() => searchInput.value?.el?.focus?.())
}

function onEnter() {
  if (creating.value) return
  const visible = groups.value.flatMap((g) => g.tags)
  if (visible.length == 1 && !canCreate.value) toggleTag(visible[0].name)
  else if (canCreate.value) startCreate()
}

function startCreate() {
  newCategory.value = ''
  newColor.value = 'blue'
  creating.value = true
}

async function run(method, params) {
  busy.value = true
  try {
    docTags.data = await call(method, {
      doctype: props.doctype,
      name: props.docname,
      ...params,
    })
    allTags.reload()
    return true
  } catch (e) {
    toast.error(e?.messages?.[0] || e?.message || __('Could not update tags'))
    return false
  } finally {
    busy.value = false
  }
}

function toggleTag(name) {
  if (applied.value.has(name)) return removeTag(name)
  return run('abm_crm.api.tags.add_tag', { tag: name })
}

function removeTag(name) {
  return run('abm_crm.api.tags.remove_tag', { tag: name })
}

async function createTag(close) {
  const tag = query.value.trim()
  if (!tag) return
  const ok = await run('abm_crm.api.tags.add_tag', {
    tag,
    category: newCategory.value || null,
    color: newColor.value || null,
  })
  if (ok) {
    query.value = ''
    creating.value = false
    close?.()
  }
}
</script>
