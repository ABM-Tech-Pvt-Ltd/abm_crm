<template>
  <!-- abm_crm: site visits of a lead or deal: schedule, edit, mark visited, postpone, cancel -->
  <div class="flex flex-col gap-3 px-3 pb-5 sm:px-10">
    <div class="flex items-center justify-between gap-3">
      <span class="text-sm text-ink-gray-5">{{ __('Site visits, walk-ins and office meetings') }}</span>
      <Button variant="solid" iconLeft="plus" :label="__('Schedule visit')" @click="dialogs.create(doctype, docname)" />
    </div>
    <div v-if="visits.loading && !visits.data" class="py-10 text-center text-ink-gray-5">
      {{ __('Loading...') }}
    </div>
    <div
      v-else-if="!visits.data?.length"
      class="flex flex-col items-center justify-center gap-3 py-16 text-ink-gray-4"
    >
      <VisitIcon class="size-10" />
      <span class="text-lg font-medium">{{ __('No site visits') }}</span>
      <span class="text-center text-base">{{ __('Schedule a visit here, or check in from the mobile app.') }}</span>
    </div>
    <VisitCard
      v-for="visit in visits.data || []"
      v-else
      :key="visit.name"
      :visit="visit"
      @edit="(v) => dialogs.edit(v)"
      @action="(v, s) => dialogs.action(v, s)"
      @delete="(v) => dialogs.remove(v)"
    />
    <VisitDialogs ref="dialogs" @changed="reload" />
  </div>
</template>

<script setup>
import VisitIcon from '@/components/Icons/VisitIcon.vue'
import { Button, createResource } from 'frappe-ui'
import { ref, watch } from 'vue'
import VisitCard from './VisitCard.vue'
import VisitDialogs from './VisitDialogs.vue'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
})

const dialogs = ref(null)
const visits = createResource({
  url: 'abm_crm.api.visits.get_visits',
  cache: ['abm_field_visits', props.doctype, props.docname],
  makeParams: () => ({ doctype: props.doctype, name: props.docname }),
  auto: true,
})

function reload() {
  visits.reload()
  // the Activity timeline keeps its own copy
  window.dispatchEvent(new CustomEvent('abm-visits-changed'))
}

watch(
  () => props.docname,
  () => visits.reload(),
)

defineExpose({ reload })
</script>
