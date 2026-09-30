<template>
  <div class="flex h-full flex-col gap-6 py-8 px-6 text-ink-gray-8">
    <div class="flex justify-between px-2">
      <div class="flex flex-col gap-1">
        <h2 class="flex gap-2 text-2xl-semibold leading-none h-5">
          {{ __('Email Senders') }}
        </h2>
        <p class="text-p-base text-ink-gray-6">
          {{
            __(
              'Choose which email accounts each user or role can send from in the lead and deal email composer',
            )
          }}
        </p>
      </div>
      <Button
        :label="__('New')"
        iconLeft="plus"
        variant="solid"
        :disabled="!accounts.length"
        @click="openForm()"
      />
    </div>

    <div v-if="setup.loading && !setup.data" class="flex mt-28 w-full">
      <Button :loading="true" variant="ghost" class="w-full" size="2xl" />
    </div>

    <div v-else class="flex-1 flex flex-col gap-6 overflow-y-auto">
      <!-- no outgoing accounts yet -->
      <div
        v-if="!accounts.length"
        class="mx-2 flex items-center justify-between gap-4 rounded-md bg-surface-amber-1 p-3 text-p-sm text-ink-amber-3"
      >
        <span>
          {{
            __(
              'No email account with outgoing enabled. Add one in Email Accounts first.',
            )
          }}
        </span>
        <Button
          :label="__('Email Accounts')"
          @click="activeSettingsPage = 'Accounts'"
        />
      </div>

      <!-- rules -->
      <div class="flex flex-col">
        <div
          v-if="!rules.length && accounts.length"
          class="px-2 py-6 text-center text-p-base text-ink-gray-5"
        >
          {{
            __(
              'No sender rules yet. Without rules, users can send from their own email accounts and the default outgoing account.',
            )
          }}
        </div>
        <template v-for="(rule, i) in rules" :key="rule.name">
          <div v-if="i" class="h-px border-t mx-2 border-outline-gray-modals" />
          <div class="flex items-center justify-between gap-4 py-3 px-2">
            <div class="flex min-w-0 flex-col">
              <div class="flex items-center gap-2 text-p-base-medium text-ink-gray-7">
                <span class="truncate">{{ rule.email_id || rule.email_account }}</span>
                <Badge v-if="rule.is_default" :label="__('Default')" theme="blue" />
              </div>
              <div class="truncate text-p-sm text-ink-gray-5">
                {{ appliesToLabel(rule) }}
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <Switch
                :modelValue="Boolean(rule.enabled)"
                size="sm"
                @update:modelValue="(v) => saveRule({ ...rule, enabled: v ? 1 : 0 })"
              />
              <Button variant="ghost" icon="edit-2" @click="openForm(rule)" />
              <Button variant="ghost" icon="trash-2" @click="deleteRule(rule)" />
            </div>
          </div>
        </template>
      </div>

      <!-- settings -->
      <div class="flex flex-col">
        <div class="px-2 pb-1 text-p-base-medium text-ink-gray-8">
          {{ __('Options') }}
        </div>
        <template v-for="(option, i) in options" :key="option.field">
          <div v-if="i" class="h-px border-t mx-2 border-outline-gray-modals" />
          <div class="flex items-center justify-between gap-4 py-3 px-2">
            <div class="flex flex-col">
              <div class="text-p-base-medium text-ink-gray-7">
                {{ option.label }}
              </div>
              <div class="text-p-sm text-ink-gray-5">
                {{ option.description }}
              </div>
            </div>
            <Switch
              :modelValue="Boolean(settings[option.field])"
              size="sm"
              @update:modelValue="(v) => updateSetting(option.field, v)"
            />
          </div>
        </template>
      </div>
    </div>

    <Dialog
      v-model:open="showForm"
      :title="form.name ? __('Edit Sender') : __('New Sender')"
    >
      <template #default>
        <div class="flex flex-col gap-4">
          <FormControl
            v-model="form.email_account"
            type="select"
            :label="__('Email Account')"
            :options="accountOptions"
          />
          <FormControl
            v-model="form.applies_to"
            type="select"
            :label="__('Applies To')"
            :options="appliesToOptions"
          />
          <FormControl
            v-if="form.applies_to == 'User'"
            v-model="form.user"
            type="select"
            :label="__('User')"
            :options="userOptions"
          />
          <FormControl
            v-if="form.applies_to == 'Role'"
            v-model="form.role"
            type="select"
            :label="__('Role')"
            :options="roleOptions"
          />
          <FormControl
            v-model="form.is_default"
            type="checkbox"
            :label="__('Pre-select this sender in the composer')"
          />
        </div>
      </template>
      <template #actions>
        <Button
          class="w-full"
          variant="solid"
          :label="__('Save')"
          :loading="saving"
          @click="submitForm"
        />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { activeSettingsPage } from '@/composables/settings'
import {
  Badge,
  Button,
  Dialog,
  FormControl,
  Switch,
  call,
  createResource,
  toast,
} from 'frappe-ui'
import { computed, ref } from 'vue'

const setup = createResource({
  url: 'abm_crm.api.email.get_sender_setup',
  cache: 'abm_crm_sender_setup',
  auto: true,
})

const accounts = computed(() => setup.data?.accounts || [])
const rules = computed(() => setup.data?.rules || [])
const settings = computed(() => setup.data?.settings || {})

const accountOptions = computed(() =>
  accounts.value.map((a) => ({
    label: `${a.name} <${a.email_id}>`,
    value: a.name,
  })),
)
const userOptions = computed(() =>
  (setup.data?.users || []).map((u) => ({
    label: u.full_name ? `${u.full_name} (${u.name})` : u.name,
    value: u.name,
  })),
)
const roleOptions = computed(() =>
  (setup.data?.roles || []).map((r) => ({ label: __(r), value: r })),
)
const appliesToOptions = [
  { label: __('User'), value: 'User' },
  { label: __('Role'), value: 'Role' },
  { label: __('Everyone'), value: 'Everyone' },
]

const options = [
  {
    field: 'include_user_email_accounts',
    label: __("Include user's own email accounts"),
    description: __(
      'Also offer the accounts linked to each user under User > Email',
    ),
  },
  {
    field: 'include_default_outgoing',
    label: __('Include default outgoing account'),
    description: __("Also offer the site's default outgoing email account"),
  },
  {
    field: 'enforce_sender_rules',
    label: __('Enforce sender rules'),
    description: __(
      'Block emails sent from any address the user is not allowed to use. System Managers are exempt.',
    ),
  },
]

function appliesToLabel(rule) {
  if (rule.applies_to == 'User') return __('User: {0}', [rule.user])
  if (rule.applies_to == 'Role') return __('Role: {0}', [__(rule.role)])
  return __('Everyone')
}

const showForm = ref(false)
const saving = ref(false)
const form = ref({})

function openForm(rule) {
  form.value = rule
    ? { ...rule, is_default: Boolean(rule.is_default) }
    : {
        enabled: 1,
        email_account: accounts.value[0]?.name,
        applies_to: 'User',
        user: '',
        role: '',
        is_default: false,
      }
  showForm.value = true
}

async function submitForm() {
  saving.value = true
  try {
    await saveRule({ ...form.value, is_default: form.value.is_default ? 1 : 0 })
    showForm.value = false
  } finally {
    saving.value = false
  }
}

async function saveRule(rule) {
  try {
    await call('abm_crm.api.email.save_sender_rule', { rule })
    toast.success(__('Sender saved'))
  } catch (err) {
    toast.error(err.messages?.[0] || __('Could not save sender'))
    throw err
  } finally {
    setup.reload()
  }
}

async function deleteRule(rule) {
  await call('abm_crm.api.email.delete_sender_rule', { name: rule.name })
  toast.success(__('Sender removed'))
  setup.reload()
}

async function updateSetting(field, value) {
  await call('abm_crm.api.email.update_sender_setting', {
    field,
    value: value ? 1 : 0,
  })
  setup.reload()
}
</script>
