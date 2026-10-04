<template>
  <!-- abm_crm: call / WhatsApp / email shortcuts for a lead or deal -->
  <div
    v-if="variant == 'bar'"
    class="grid grid-cols-3 gap-2 border-b px-3 py-2.5"
  >
    <a
      v-for="action in actions"
      :key="action.label"
      :href="action.href"
      :target="action.target"
      rel="noopener"
      class="flex h-11 items-center justify-center gap-2 rounded-lg text-base-medium active:scale-[0.98] transition"
      :class="
        action.disabled
          ? 'pointer-events-none bg-surface-gray-2 text-ink-gray-4'
          : action.class
      "
      @click="(e) => action.onClick?.(e)"
    >
      <component :is="action.icon" class="size-4" />
      <span>{{ action.label }}</span>
    </a>
  </div>
  <template v-else>
    <Tooltip v-for="action in actions" :key="action.label" :text="action.label">
      <a
        :href="action.href"
        :target="action.target"
        rel="noopener"
        :aria-label="action.label"
        class="inline-flex size-7 items-center justify-center rounded bg-surface-gray-2 text-ink-gray-7 hover:bg-surface-gray-3"
        :class="{ 'pointer-events-none opacity-40': action.disabled }"
        @click="(e) => action.onClick?.(e)"
      >
        <component :is="action.icon" class="size-4" />
      </a>
    </Tooltip>
  </template>
</template>

<script setup>
import PhoneIcon from '@/components/Icons/PhoneIcon.vue'
import WhatsAppIcon from '@/components/Icons/WhatsAppIcon.vue'
import Email2Icon from '@/components/Icons/Email2Icon.vue'
import { Tooltip, createResource } from 'frappe-ui'
import { computed, watch } from 'vue'

const props = defineProps({
  doctype: { type: String, required: true },
  docname: { type: String, required: true },
  // re-fetch the links when the number or email on the record changes
  phone: { type: String, default: '' },
  email: { type: String, default: '' },
  variant: { type: String, default: 'icons' }, // 'icons' (desktop) | 'bar' (mobile)
})
const emit = defineEmits(['email'])

const links = createResource({
  url: 'abm_crm.api.quick_whatsapp.get_contact_links',
  makeParams: () => ({ doctype: props.doctype, name: props.docname }),
  cache: ['abm_contact_links', props.doctype, props.docname],
  auto: true,
})

watch(
  () => [props.phone, props.email, props.docname],
  () => links.reload(),
)

const actions = computed(() => {
  const data = links.data || {}
  return [
    {
      label: __('Call'),
      icon: PhoneIcon,
      href: data.tel ? `tel:${data.tel}` : undefined,
      disabled: !data.tel,
      class: 'bg-surface-gray-2 text-ink-gray-8',
    },
    {
      label: __('WhatsApp'),
      icon: WhatsAppIcon,
      href: data.wa_number ? `https://wa.me/${data.wa_number}` : undefined,
      target: '_blank',
      disabled: !data.wa_number,
      class: 'bg-[#25D366] text-white',
    },
  ]
})
</script>
