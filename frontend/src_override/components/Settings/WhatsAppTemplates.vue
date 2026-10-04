<template>
  <div class="flex h-full flex-col gap-6 py-8 px-6 text-ink-gray-8">
    <div class="flex justify-between gap-4 px-2">
      <div class="flex flex-col gap-1">
        <h2 class="flex gap-2 text-2xl-semibold leading-none h-5">
          {{ __('WhatsApp Templates') }}
        </h2>
        <p class="text-p-base text-ink-gray-6">
          {{
            __(
              'Predefined messages reps can send from the WhatsApp tab of a lead or deal with one tap.',
            )
          }}
        </p>
      </div>
      <Button
        :label="__('New Template')"
        iconLeft="plus"
        variant="solid"
        @click="openForm()"
      />
    </div>

    <div v-if="setup.loading && !setup.data" class="flex mt-28 w-full">
      <Button :loading="true" variant="ghost" class="w-full" size="2xl" />
    </div>

    <div v-else class="flex flex-1 flex-col gap-6 overflow-y-auto">
      <!-- mode -->
      <div class="flex flex-col gap-2 px-2">
        <div class="text-p-base-medium text-ink-gray-8">
          {{ __('How WhatsApp messages are sent') }}
        </div>
        <div class="grid gap-2 sm:grid-cols-2">
          <button
            v-for="m in modes"
            :key="m.value"
            class="flex flex-col gap-1 rounded-lg border p-3 text-left transition"
            :class="
              mode == m.value
                ? 'border-outline-gray-5 bg-surface-gray-1'
                : 'border-outline-gray-2 hover:border-outline-gray-3'
            "
            :disabled="m.disabled"
            @click="setMode(m.value)"
          >
            <span class="flex items-center gap-2 text-p-base-medium text-ink-gray-8">
              {{ m.label }}
              <Badge v-if="mode == m.value" :label="__('Active')" theme="green" />
            </span>
            <span class="text-p-sm text-ink-gray-5">{{ m.description }}</span>
          </button>
        </div>
      </div>

      <!-- templates -->
      <div class="flex flex-col">
        <div
          v-if="!templates.length"
          class="px-2 py-6 text-center text-p-base text-ink-gray-5"
        >
          {{ __('No templates yet.') }}
        </div>
        <template v-for="(t, i) in templates" :key="t.name">
          <div v-if="i" class="h-px border-t mx-2 border-outline-gray-modals" />
          <div class="flex items-center justify-between gap-4 py-3 px-2">
            <div class="flex min-w-0 flex-col gap-1">
              <div class="flex items-center gap-2 text-p-base-medium text-ink-gray-7">
                <span class="truncate">{{ t.template_name }}</span>
                <Badge
                  v-if="t.applies_to != 'Both'"
                  :label="t.applies_to == 'CRM Lead' ? __('Leads') : __('Deals')"
                  theme="gray"
                />
              </div>
              <div class="line-clamp-2 text-p-sm text-ink-gray-5">
                {{ t.message }}
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <Switch
                :modelValue="Boolean(t.enabled)"
                size="sm"
                @update:modelValue="(v) => save({ ...t, enabled: v ? 1 : 0 })"
              />
              <Button variant="ghost" icon="edit-2" @click="openForm(t)" />
              <Button variant="ghost" icon="trash-2" @click="remove(t)" />
            </div>
          </div>
        </template>
      </div>
    </div>

    <Dialog
      v-model:open="showForm"
      :title="form.name ? __('Edit Template') : __('New Template')"
    >
      <template #default>
        <div class="flex flex-col gap-4">
          <FormControl
            v-model="form.template_name"
            type="text"
            :label="__('Template Name')"
            :placeholder="__('Introduction')"
          />
          <div class="grid grid-cols-2 gap-3">
            <FormControl
              v-model="form.applies_to"
              type="select"
              :label="__('Show On')"
              :options="[
                { label: __('Leads and Deals'), value: 'Both' },
                { label: __('Leads'), value: 'CRM Lead' },
                { label: __('Deals'), value: 'CRM Deal' },
              ]"
            />
            <FormControl
              v-model="form.sort_order"
              type="number"
              :label="__('Order')"
            />
          </div>
          <FormControl
            v-model="form.message"
            type="textarea"
            :rows="6"
            :label="__('Message')"
          />
          <div class="flex flex-col gap-1.5">
            <span class="text-p-sm text-ink-gray-5">
              {{ __('Tap to insert:') }}
            </span>
            <div class="flex flex-wrap gap-1">
              <Button
                v-for="p in placeholders"
                :key="p.value"
                size="sm"
                variant="subtle"
                :label="p.label"
                @click="insert(p.value)"
              />
            </div>
          </div>
          <ErrorMessage :message="formError" />
        </div>
      </template>
      <template #actions>
        <Button
          class="w-full"
          variant="solid"
          :label="__('Save')"
          :loading="saving"
          @click="submit"
        />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { reloadWhatsappMode } from '@/composables/whatsapp'
import {
  Badge,
  Button,
  Dialog,
  ErrorMessage,
  FormControl,
  Switch,
  call,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, ref } from 'vue'

const setup = createResource({
  url: 'abm_crm.api.quick_whatsapp.get_template_setup',
  cache: 'abm_whatsapp_template_setup',
  auto: true,
})
const templates = computed(() => setup.data?.templates || [])
const mode = computed(() => setup.data?.mode || 'Click to Chat')

const modes = computed(() => [
  {
    value: 'Click to Chat',
    label: __('Click to Chat (free)'),
    description: __(
      "Opens the rep's own WhatsApp app or WhatsApp Web with the message typed in. No Meta account needed. Replies stay in WhatsApp.",
    ),
  },
  {
    value: 'Cloud API',
    label: __('WhatsApp Cloud API'),
    description: setup.data?.cloud_installed
      ? __(
          'Send and receive inside the CRM through Meta. Needs a WhatsApp Business account; template messages are charged by Meta.',
        )
      : __('Install the frappe_whatsapp app to use this.'),
    disabled: !setup.data?.cloud_installed,
  },
])

const placeholders = [
  { label: __('First name'), value: "{{ doc.first_name or '' }}" },
  { label: __('Full name'), value: '{{ doc.lead_name or doc.organization }}' },
  { label: __('Organization'), value: "{{ doc.organization or '' }}" },
  { label: __('My name'), value: '{{ user.first_name }}' },
  { label: __('Company'), value: '{{ brand }}' },
]

async function setMode(value) {
  if (value == mode.value) return
  await call('abm_crm.api.quick_whatsapp.set_whatsapp_mode', { mode: value })
  await setup.reload()
  reloadWhatsappMode()
  toast.success(__('WhatsApp mode set to {0}', [value]))
}

const showForm = ref(false)
const saving = ref(false)
const formError = ref('')
const form = ref({})

function openForm(t) {
  formError.value = ''
  form.value = t
    ? { ...t }
    : {
        template_name: '',
        applies_to: 'Both',
        enabled: 1,
        sort_order: templates.value.length,
        message: '',
      }
  showForm.value = true
}

function insert(value) {
  form.value.message = `${form.value.message || ''}${value}`
}

async function save(t) {
  await call('abm_crm.api.quick_whatsapp.save_template', { template: t })
  setup.reload()
}

async function submit() {
  formError.value = ''
  if (!form.value.template_name?.trim() || !form.value.message?.trim()) {
    formError.value = __('Name and message are required')
    return
  }
  saving.value = true
  try {
    await save({ ...form.value, sort_order: Number(form.value.sort_order) || 0 })
    toast.success(__('Template saved'))
    showForm.value = false
  } catch (err) {
    formError.value = err?.messages?.[0] || __('Could not save template')
  } finally {
    saving.value = false
  }
}

async function remove(t) {
  if (!window.confirm(__('Delete template {0}?', [t.template_name]))) return
  await call('abm_crm.api.quick_whatsapp.delete_template', { name: t.name })
  setup.reload()
}
</script>
