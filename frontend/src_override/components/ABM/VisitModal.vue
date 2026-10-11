<template>
  <!-- abm_crm: schedule or edit a site visit -->
  <Dialog v-model:open="open" :title="visit ? __('Edit visit') : __('Schedule visit')" :size="'3xl'">
    <template #default>
      <div class="flex max-h-[68vh] flex-col gap-4 overflow-y-auto px-0.5 pb-24">
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormControl v-model="form.visit_type" type="select" :label="__('Type')" :options="typeOptions" />
          <FormControl v-model="form.status" type="select" :label="__('Status')" :options="statusOptions" />
          <div class="sm:col-span-2">
            <label class="mb-1.5 block text-xs text-ink-gray-5">{{ __('Project') }}</label>
            <input
              v-model="form.project"
              list="abm-visit-projects"
              class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
              :placeholder="__('Pick a project or type one')"
            />
            <datalist id="abm-visit-projects">
              <option v-for="p in projects" :key="p" :value="p" />
            </datalist>
          </div>
          <label class="flex flex-col gap-1.5 text-xs text-ink-gray-5">
            {{ __('Scheduled date') }}{{ needsDate ? ' *' : '' }}
            <input v-model="form.date" type="date" class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3" />
          </label>
          <label class="flex flex-col gap-1.5 text-xs text-ink-gray-5">
            {{ __('Time') }}
            <input v-model="form.time" type="time" class="h-7 w-full rounded border border-outline-gray-2 bg-surface-white px-2 text-base text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none focus:ring-2 focus:ring-outline-gray-3" />
          </label>
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <PersonInput
            v-for="r in ROLES"
            :key="r.key"
            v-model:name="form[r.key]"
            v-model:user="form[r.key + '_user']"
            :label="__(r.label)"
            :users="users"
          />
        </div>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FormControl v-model="form.outcome" type="select" :label="__('Outcome')" :options="outcomeOptions" />
          <FormControl
            v-if="['Cancelled', 'Postponed', 'No Show'].includes(form.status)"
            v-model="form.status_reason"
            type="text"
            :label="__('Reason')"
          />
        </div>
        <FormControl v-model="form.notes" type="textarea" :rows="3" :label="__('Notes')" />
        <ErrorMessage :message="error" />
      </div>
    </template>
    <template #actions>
      <Button class="w-full" variant="solid" :label="__('Save')" :loading="saving" @click="submit" />
    </template>
  </Dialog>
</template>

<script setup>
import { Button, Dialog, ErrorMessage, FormControl, call, toast } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import PersonInput from './PersonInput.vue'
import {
  NEEDS_DATE,
  ROLES,
  errorText,
  joinDateTime,
  toDateInput,
  toTimeInput,
  useVisitOptions,
} from './visits.js'

const open = defineModel('open', { type: Boolean, default: false })
const props = defineProps({
  visit: { type: Object, default: null }, // edit
  doctype: String, // create
  docname: String,
})
const emit = defineEmits(['saved'])

const { statuses, types, outcomes, projects, users } = useVisitOptions()
const statusOptions = computed(() => statuses.value.map((s) => ({ label: __(s.name), value: s.name })))
const typeOptions = computed(() => types.value.map((t) => ({ label: __(t), value: t })))
const outcomeOptions = computed(() =>
  outcomes.value.map((o) => ({ label: o ? __(o) : __('Not set'), value: o })),
)

const form = ref({})
const error = ref('')
const saving = ref(false)
const needsDate = computed(() => NEEDS_DATE.includes(form.value.status))

watch(open, (v) => {
  if (!v) return
  error.value = ''
  const x = props.visit
  form.value = {
    visit_type: x?.visit_type || 'Site Visit',
    status: x?.status || 'Scheduled',
    project: x?.project || '',
    date: toDateInput(x?.scheduled_on),
    time: toTimeInput(x?.scheduled_on) || '10:00',
    outcome: x?.outcome || '',
    status_reason: x?.status_reason || '',
    notes: x?.notes || '',
  }
  for (const r of ROLES) {
    form.value[r.key] = x?.[r.key + '_name'] || x?.[r.key] || ''
    form.value[r.key + '_user'] = x?.[r.key + '_user'] || ''
  }
})

async function submit() {
  error.value = ''
  const f = form.value
  if (needsDate.value && !f.date) {
    error.value = __('{0} visits need a scheduled date', [__(f.status)])
    return
  }
  const data = {
    status: f.status,
    visit_type: f.visit_type,
    project: f.project || '',
    scheduled_on: joinDateTime(f.date, f.time),
    outcome: f.outcome || '',
    status_reason: f.status_reason || '',
    notes: f.notes || '',
  }
  for (const r of ROLES) {
    // a picked user sends the user (the server fills the name); a typed name sends only the name
    if (f[r.key + '_user']) {
      data[r.key + '_user'] = f[r.key + '_user']
    } else {
      data[r.key + '_user'] = ''
      data[r.key] = f[r.key] || ''
    }
  }
  saving.value = true
  try {
    const res = props.visit
      ? await call('abm_crm.api.visits.update_visit', { name: props.visit.name, data })
      : await call('abm_crm.api.visits.create_visit', {
          reference_doctype: props.doctype,
          reference_docname: props.docname,
          data,
        })
    toast.success(props.visit ? __('Visit updated') : __('Visit scheduled'))
    open.value = false
    emit('saved', res)
  } catch (err) {
    error.value = errorText(err, __('Could not save the visit'))
  } finally {
    saving.value = false
  }
}
</script>
