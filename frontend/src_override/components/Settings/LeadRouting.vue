<template>
  <div class="flex h-full flex-col gap-6 py-8 px-6 text-ink-gray-8">
    <div class="flex justify-between gap-4 px-2">
      <div class="flex flex-col gap-1">
        <h2 class="flex gap-2 text-2xl-semibold leading-none h-5">
          {{ __('Lead Routing') }}
        </h2>
        <p class="text-p-base text-ink-gray-6">
          {{
            __(
              'Assign new leads to specific users by campaign, ad set, ad, lead form, source or platform. The first matching rule (highest priority) wins.',
            )
          }}
        </p>
      </div>
      <Button
        :label="__('New Rule')"
        iconLeft="plus"
        variant="solid"
        @click="openForm()"
      />
    </div>

    <div v-if="setup.loading && !setup.data" class="flex mt-28 w-full">
      <Button :loading="true" variant="ghost" class="w-full" size="2xl" />
    </div>

    <div v-else class="flex-1 flex flex-col gap-6 overflow-y-auto">
      <!-- rules -->
      <div class="flex flex-col">
        <div
          v-if="!rules.length"
          class="px-2 py-8 text-center text-p-base text-ink-gray-5"
        >
          {{
            __(
              'No routing rules yet. Create one, for example: leads from campaign "Diwali" go to Sarah and John in turn.',
            )
          }}
        </div>
        <template v-for="(rule, i) in rules" :key="rule.name">
          <div v-if="i" class="h-px border-t mx-2 border-outline-gray-modals" />
          <div class="flex items-center justify-between gap-4 py-3 px-2">
            <div class="flex min-w-0 flex-col gap-1.5">
              <div class="flex items-center gap-2 text-p-base-medium text-ink-gray-7">
                <span class="truncate">{{ rule.rule_name }}</span>
                <Badge :label="__('Priority {0}', [rule.priority])" theme="gray" />
                <Badge :label="__(rule.strategy)" theme="blue" />
              </div>
              <div class="flex flex-wrap gap-1">
                <Badge
                  v-for="c in conditionChips(rule)"
                  :key="c"
                  :label="c"
                  variant="outline"
                  theme="gray"
                />
              </div>
              <div class="truncate text-p-sm text-ink-gray-5">
                {{ usersSummary(rule) }}
                <template v-if="rule.assigned_count">
                  · {{ __('{0} leads assigned', [rule.assigned_count]) }}
                </template>
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <Switch
                :modelValue="Boolean(rule.enabled)"
                size="sm"
                @update:modelValue="(v) => setEnabled(rule, v)"
              />
              <Button variant="ghost" icon="edit-2" @click="openForm(rule)" />
              <Button variant="ghost" icon="trash-2" @click="deleteRule(rule)" />
            </div>
          </div>
        </template>
      </div>

      <!-- dry run -->
      <div class="flex flex-col gap-2 px-2">
        <div class="text-p-base-medium text-ink-gray-8">
          {{ __('Test with an existing lead') }}
        </div>
        <div class="flex items-center gap-2">
          <FormControl
            v-model="testLead"
            type="text"
            class="w-64"
            :placeholder="__('Lead ID, e.g. CRM-LEAD-2026-00001')"
            @keydown.enter="runTest"
          />
          <Button :label="__('Test')" :loading="testing" @click="runTest" />
        </div>
        <div v-if="testResult" class="text-p-sm text-ink-gray-6">
          {{ testResult }}
        </div>
      </div>
    </div>

    <Dialog
      v-model:open="showForm"
      :title="form.name ? __('Edit Routing Rule') : __('New Routing Rule')"
      :size="'3xl'"
    >
      <template #default>
        <div class="flex max-h-[65vh] flex-col gap-5 overflow-y-auto pr-1">
          <div class="grid grid-cols-3 gap-3">
            <FormControl
              v-model="form.rule_name"
              class="col-span-2"
              type="text"
              :label="__('Rule Name')"
              :placeholder="__('Diwali campaign - Delhi team')"
            />
            <FormControl
              v-model="form.priority"
              type="number"
              :label="__('Priority (higher first)')"
            />
          </div>

          <!-- conditions -->
          <div class="flex flex-col gap-3">
            <div>
              <div class="text-p-base-medium text-ink-gray-8">
                {{ __('When a new lead matches') }}
              </div>
              <div class="text-p-sm text-ink-gray-5">
                {{ __('Leave a field empty to match anything. All filled fields must match.') }}
              </div>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <FormControl
                v-model="form.lead_sync_source"
                type="select"
                :label="__('Lead Sync Source')"
                :options="withAny(syncSourceOptions)"
              />
              <FormControl
                v-model="form.facebook_lead_form"
                type="select"
                :label="__('Facebook Lead Form')"
                :options="withAny(formOptions)"
              />
              <FormControl
                v-model="form.lead_source"
                type="select"
                :label="__('Lead Source')"
                :options="withAny(toOptions(setup.data?.lead_sources))"
              />
              <FormControl
                v-model="form.platform"
                type="select"
                :label="__('Platform')"
                :options="withAny(toOptions(platforms))"
              />
              <FormControl
                v-model="form.territory"
                type="select"
                :label="__('Territory')"
                :options="withAny(toOptions(setup.data?.territories))"
              />
              <FormControl
                v-model="form.campaign_match"
                type="select"
                :label="__('Match campaign / ad set / ad by')"
                :options="toOptions(['Contains', 'Equals', 'Starts With'])"
              />
            </div>

            <div
              v-for="t in textConditions"
              :key="t.field"
              class="flex flex-col gap-1.5"
            >
              <FormControl
                v-model="form[t.field]"
                type="text"
                :label="t.label"
                :placeholder="__('Name or ID. Separate several with commas.')"
              />
              <div v-if="suggestions(t).length" class="flex flex-wrap gap-1">
                <Button
                  v-for="s in suggestions(t)"
                  :key="s"
                  size="sm"
                  variant="subtle"
                  :label="s"
                  @click="addValue(t.field, s)"
                />
              </div>
            </div>

            <FormControl
              v-model="form.condition"
              type="textarea"
              :label="__('Extra condition (advanced, optional)')"
              :placeholder="__('doc.country == &quot;India&quot; and doc.industry == &quot;Retail&quot;')"
            />
          </div>

          <!-- assignment -->
          <div class="flex flex-col gap-3">
            <div class="text-p-base-medium text-ink-gray-8">
              {{ __('Assign to') }}
            </div>
            <div class="grid grid-cols-2 gap-3">
              <FormControl
                v-model="form.strategy"
                type="select"
                :label="__('Strategy')"
                :options="strategyOptions"
              />
              <FormControl
                v-model="form.fallback_user"
                type="select"
                :label="__('Fallback user (everyone busy)')"
                :options="withAny(userOptions, __('None: try next rule'))"
              />
            </div>

            <div class="flex flex-col gap-2">
              <div
                class="grid grid-cols-[1fr_7rem_6rem_2rem] items-center gap-2 text-p-sm text-ink-gray-5"
              >
                <span>{{ __('User') }}</span>
                <span>{{ __('Max open leads') }}</span>
                <span>{{ __('Active') }}</span>
                <span />
              </div>
              <div
                v-for="(row, idx) in form.users"
                :key="idx"
                class="grid grid-cols-[1fr_7rem_6rem_2rem] items-center gap-2"
              >
                <FormControl
                  v-model="row.user"
                  type="select"
                  :options="userOptions"
                />
                <FormControl
                  v-model="row.max_open_leads"
                  type="number"
                  :placeholder="__('No limit')"
                />
                <FormControl v-model="row.active" type="checkbox" />
                <Button
                  variant="ghost"
                  icon="x"
                  @click="form.users.splice(idx, 1)"
                />
              </div>
              <div>
                <Button
                  :label="__('Add User')"
                  iconLeft="plus"
                  @click="form.users.push({ user: '', active: true, max_open_leads: 0 })"
                />
              </div>
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
          @click="submitForm"
        />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
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
  url: 'abm_crm.api.lead_routing.get_routing_setup',
  cache: 'abm_crm_routing_setup',
  auto: true,
})

const rules = computed(() => setup.data?.rules || [])
const platforms = ['Facebook', 'Instagram', 'Messenger', 'WhatsApp', 'Website', 'Other']
const strategyOptions = [
  { label: __('Round Robin: take turns'), value: 'Round Robin' },
  { label: __('Load Balancing: fewest open leads'), value: 'Load Balancing' },
]
const textConditions = [
  { field: 'campaign', label: __('Campaign'), key: 'campaigns' },
  { field: 'adset', label: __('Ad Set'), key: 'adsets' },
  { field: 'ad', label: __('Ad'), key: 'ads' },
]

const toOptions = (values) => (values || []).map((v) => ({ label: __(v), value: v }))
const withAny = (options, label) => [{ label: label || __('Any'), value: '' }, ...options]

const userName = (email) =>
  setup.data?.users?.find((u) => u.name == email)?.full_name || email
const userOptions = computed(() =>
  (setup.data?.users || []).map((u) => ({
    label: u.full_name ? `${u.full_name} (${u.name})` : u.name,
    value: u.name,
  })),
)
const syncSourceOptions = computed(() =>
  (setup.data?.sync_sources || []).map((s) => ({ label: s.name, value: s.name })),
)
const formOptions = computed(() =>
  (setup.data?.facebook_forms || []).map((f) => ({
    label: f.form_name || f.name,
    value: f.name,
  })),
)

function formName(id) {
  return setup.data?.facebook_forms?.find((f) => f.name == id)?.form_name || id
}

function conditionChips(rule) {
  const chips = []
  if (rule.lead_sync_source) chips.push(__('Sync: {0}', [rule.lead_sync_source]))
  if (rule.facebook_lead_form)
    chips.push(__('Form: {0}', [formName(rule.facebook_lead_form)]))
  if (rule.lead_source) chips.push(__('Source: {0}', [rule.lead_source]))
  if (rule.platform) chips.push(__('Platform: {0}', [rule.platform]))
  if (rule.territory) chips.push(__('Territory: {0}', [rule.territory]))
  const how = __(rule.campaign_match || 'Contains').toLowerCase()
  if (rule.campaign) chips.push(__('Campaign {0} {1}', [how, rule.campaign]))
  if (rule.adset) chips.push(__('Ad set {0} {1}', [how, rule.adset]))
  if (rule.ad) chips.push(__('Ad {0} {1}', [how, rule.ad]))
  if (rule.condition) chips.push(__('Extra condition'))
  if (!chips.length) chips.push(__('Every new lead'))
  return chips
}

function usersSummary(rule) {
  const active = rule.users.filter((u) => u.active)
  const names = active.map((u) =>
    u.max_open_leads
      ? `${userName(u.user)} (${__('max {0}', [u.max_open_leads])})`
      : userName(u.user),
  )
  let text = names.length
    ? __('Assigns to {0}', [names.join(', ')])
    : __('No active users')
  if (rule.fallback_user) text += ` · ${__('fallback {0}', [userName(rule.fallback_user)])}`
  return text
}

function suggestions(t) {
  const current = (form.value[t.field] || '')
    .split(',')
    .map((v) => v.trim().toLowerCase())
  return (setup.data?.[t.key] || [])
    .filter((v) => !current.includes(v.toLowerCase()))
    .slice(0, 8)
}

function addValue(field, value) {
  const parts = (form.value[field] || '')
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean)
  parts.push(value)
  form.value[field] = parts.join(', ')
}

const showForm = ref(false)
const saving = ref(false)
const formError = ref('')
const form = ref({})

function openForm(rule) {
  formError.value = ''
  form.value = rule
    ? {
        ...rule,
        users: rule.users.map((u) => ({ ...u, active: Boolean(u.active) })),
      }
    : {
        rule_name: '',
        enabled: 1,
        priority: 10,
        campaign_match: 'Contains',
        strategy: 'Round Robin',
        users: [{ user: '', active: true, max_open_leads: 0 }],
      }
  showForm.value = true
}

async function submitForm() {
  formError.value = ''
  if (!form.value.rule_name?.trim()) {
    formError.value = __('Rule name is required')
    return
  }
  const users = form.value.users.filter((u) => u.user)
  if (!users.length) {
    formError.value = __('Add at least one user')
    return
  }
  saving.value = true
  try {
    await call('abm_crm.api.lead_routing.save_routing_rule', {
      rule: {
        ...form.value,
        priority: Number(form.value.priority) || 0,
        users: users.map((u) => ({
          user: u.user,
          active: u.active ? 1 : 0,
          max_open_leads: Number(u.max_open_leads) || 0,
        })),
      },
    })
    toast.success(__('Routing rule saved'))
    showForm.value = false
    setup.reload()
  } catch (err) {
    formError.value = err?.messages?.[0] || __('Could not save routing rule')
  } finally {
    saving.value = false
  }
}

async function setEnabled(rule, value) {
  await call('abm_crm.api.lead_routing.set_rule_enabled', {
    name: rule.name,
    enabled: value ? 1 : 0,
  })
  setup.reload()
}

async function deleteRule(rule) {
  if (!window.confirm(__('Delete routing rule {0}?', [rule.rule_name]))) return
  await call('abm_crm.api.lead_routing.delete_routing_rule', { name: rule.name })
  toast.success(__('Routing rule deleted'))
  setup.reload()
}

const testLead = ref('')
const testing = ref(false)
const testResult = ref('')

async function runTest() {
  if (!testLead.value.trim()) return
  testing.value = true
  try {
    const res = await call('abm_crm.api.lead_routing.test_routing', {
      lead: testLead.value.trim(),
    })
    testResult.value = res.message
  } catch (err) {
    testResult.value = err?.messages?.[0] || __('Lead not found')
  } finally {
    testing.value = false
  }
}
</script>
