<template>
  <!-- abm_crm: mark visited / postpone / cancel / no show -->
  <Dialog v-model:open="open" :title="title" :size="'md'">
    <template #default>
      <div class="flex flex-col gap-3">
        <template v-if="mode === 'Visited'">
          <FormControl v-model="form.outcome" type="select" :label="__('Outcome')" :options="outcomeOptions" />
          <FormControl v-model="form.notes" type="textarea" :rows="3" :label="__('Notes')" />
        </template>
        <template v-else-if="mode === 'Postponed'">
          <div class="grid grid-cols-2 gap-3">
            <label class="flex flex-col gap-1.5 text-xs text-ink-gray-5">
              {{ __('New date') }}
              <input v-model="form.date" type="date" class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3" />
            </label>
            <label class="flex flex-col gap-1.5 text-xs text-ink-gray-5">
              {{ __('Time') }}
              <input v-model="form.time" type="time" class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3" />
            </label>
          </div>
          <FormControl v-model="form.reason" type="textarea" :rows="2" :label="__('Reason')" />
        </template>
        <template v-else>
          <FormControl v-model="form.reason" type="textarea" :rows="2" :label="__('Reason')" />
        </template>
        <ErrorMessage :message="error" />
      </div>
    </template>
    <template #actions>
      <Button class="w-full" variant="solid" :label="__('Save')" :loading="saving" @click="submit" />
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { errorText, joinDateTime, toDateInput, toTimeInput, updateVisit, useVisitOptions } from './visits.js'

const open = defineModel('open', { type: Boolean, default: false })
const props = defineProps({
  visit: { type: Object, default: null },
  mode: { type: String, default: 'Visited' }, // target status
})
const emit = defineEmits(['saved'])

const { outcomes } = useVisitOptions()
const outcomeOptions = computed(() =>
  outcomes.value.map((o) => ({ label: o ? __(o) : __('Not set'), value: o })),
)
const TITLES = {
  Visited: 'Mark visited',
  Postponed: 'Postpone visit',
  Cancelled: 'Cancel visit',
  'No Show': 'Mark as no show',
}
const title = computed(() => __(TITLES[props.mode] || 'Update visit'))

const form = ref({})
const error = ref('')
const saving = ref(false)

watch(open, (v) => {
  if (!v) return
  error.value = ''
  const vis = props.visit || {}
  form.value = {
    outcome: vis.outcome || '',
    notes: vis.notes || '',
    reason: '',
    date: toDateInput(vis.scheduled_on),
    time: toTimeInput(vis.scheduled_on) || '10:00',
  }
})

async function submit() {
  error.value = ''
  const data = { status: props.mode }
  if (props.mode === 'Visited') {
    data.outcome = form.value.outcome || ''
    data.notes = form.value.notes || ''
  } else if (props.mode === 'Postponed') {
    if (!form.value.date) {
      error.value = __('Pick the new date')
      return
    }
    data.scheduled_on = joinDateTime(form.value.date, form.value.time)
    data.status_reason = form.value.reason || ''
  } else {
    data.status_reason = form.value.reason || ''
  }
  saving.value = true
  try {
    const res = await updateVisit(props.visit.name, data)
    toast.success(__('Visit updated'))
    open.value = false
    emit('saved', res)
  } catch (err) {
    error.value = errorText(err, __('Could not update the visit'))
  } finally {
    saving.value = false
  }
}
</script>

