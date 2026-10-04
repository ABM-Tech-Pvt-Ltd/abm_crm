<template>
  <!-- abm_crm: Click to Chat WhatsApp tab. Free: opens the rep's own WhatsApp with the text typed in. -->
  <div class="flex h-full w-full flex-col gap-5 px-3 pb-6 pt-3 sm:px-10">
    <div v-if="data.loading && !data.data" class="flex justify-center py-10">
      <LoadingIndicator class="size-6 text-ink-gray-4" />
    </div>
    <template v-else>
      <div
        v-if="info.error"
        class="flex items-center justify-between gap-3 rounded-lg bg-surface-amber-1 p-3 text-p-sm text-ink-amber-3"
      >
        <span>{{ info.error }}</span>
      </div>

      <!-- composer -->
      <div class="flex flex-col gap-2">
        <div class="flex items-center justify-between">
          <span class="text-p-base-medium text-ink-gray-8">
            {{ __('Message') }}
          </span>
          <span v-if="info.wa_number" class="text-p-sm text-ink-gray-5">
            {{ __('To') }} +{{ info.wa_number }}
          </span>
        </div>
        <textarea
          ref="textarea"
          v-model="message"
          rows="5"
          class="w-full resize-none rounded-lg border border-outline-gray-2 bg-surface-white p-3 text-base text-ink-gray-8 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:ring-0"
          :placeholder="__('Pick a template below or type a message')"
        />
        <div class="flex gap-2">
          <Button
            class="flex-1 !h-10 !bg-[#25D366] !text-white hover:!bg-[#1ebe5b]"
            :disabled="!info.wa_number"
            @click="openWhatsApp"
          >
            <template #prefix>
              <WhatsAppIcon class="size-4" />
            </template>
            {{ __('Open in WhatsApp') }}
          </Button>
          <Button
            class="!h-10"
            :disabled="!message"
            :label="__('Clear')"
            @click="clear"
          />
        </div>
        <p class="text-p-xs text-ink-gray-5">
          {{
            __(
              'Opens WhatsApp on this device with the message ready. Press send in WhatsApp. The message is logged on this record.',
            )
          }}
        </p>
      </div>

      <!-- templates -->
      <div v-if="info.templates?.length" class="flex flex-col gap-2">
        <span class="text-p-base-medium text-ink-gray-8">
          {{ __('Templates') }}
        </span>
        <div class="grid gap-2 sm:grid-cols-2">
          <button
            v-for="t in info.templates"
            :key="t.name"
            class="flex flex-col gap-1 rounded-lg border p-3 text-left transition hover:border-outline-gray-4 active:scale-[0.99]"
            :class="
              selected == t.name
                ? 'border-[#25D366] bg-[#25D366]/5'
                : 'border-outline-gray-2'
            "
            @click="useTemplate(t)"
          >
            <span class="text-p-sm-medium text-ink-gray-8">{{ t.name }}</span>
            <span class="line-clamp-2 text-p-sm text-ink-gray-5">
              {{ t.message }}
            </span>
          </button>
        </div>
      </div>
      <div v-else class="text-p-sm text-ink-gray-5">
        {{ __('No templates yet. Managers can add them in Settings > WhatsApp Templates.') }}
      </div>

      <!-- history -->
      <div v-if="info.history?.length" class="flex flex-col gap-2">
        <span class="text-p-base-medium text-ink-gray-8">
          {{ __('Sent from CRM') }}
        </span>
        <div
          v-for="h in info.history"
          :key="h.name"
          class="rounded-lg bg-surface-gray-1 p-3"
        >
          <div class="whitespace-pre-wrap text-p-sm text-ink-gray-8">
            {{ h.message }}
          </div>
          <div class="mt-1.5 text-p-xs text-ink-gray-5">
            {{ getUser(h.sent_by)?.full_name || h.sent_by }} ·
            {{ formatDate(h.creation) }}
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import WhatsAppIcon from '@/components/Icons/WhatsAppIcon.vue'
import { usersStore } from '@/stores/users'
import { Button, LoadingIndicator, call, createResource, toast } from 'frappe-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
})

const { getUser } = usersStore()

const data = createResource({
  url: 'abm_crm.api.quick_whatsapp.get_quick_whatsapp',
  makeParams: () => ({ doctype: props.doctype, name: props.docname }),
  cache: ['abm_quick_whatsapp', props.doctype, props.docname],
  auto: true,
})
const info = computed(() => data.data || {})

const message = ref('')
const selected = ref('')
const textarea = ref(null)

function useTemplate(t) {
  message.value = t.message
  selected.value = t.name
  textarea.value?.focus()
}

function clear() {
  message.value = ''
  selected.value = ''
}

function openWhatsApp() {
  const number = info.value.wa_number
  if (!number) return
  const text = message.value.trim()
  const url = `https://wa.me/${number}${text ? `?text=${encodeURIComponent(text)}` : ''}`
  // open synchronously on the click, otherwise browsers block the new tab
  window.open(url, '_blank', 'noopener')
  if (!text) return
  call('abm_crm.api.quick_whatsapp.log_quick_whatsapp', {
    doctype: props.doctype,
    name: props.docname,
    message: text,
    template: selected.value || null,
  })
    .then(() => {
      clear()
      data.reload()
    })
    .catch(() => toast.error(__('Opened WhatsApp, but could not log the message')))
}

function formatDate(value) {
  return new Date(value.replace(' ', 'T')).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  })
}
</script>
