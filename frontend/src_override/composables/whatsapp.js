import { createResource } from 'frappe-ui'
import { computed, ref } from 'vue'

// abm_crm: WhatsApp has two modes (ABM CRM Settings > WhatsApp Mode).
// - "Click to Chat" (default, free): buttons open the rep's own WhatsApp with the text typed in.
// - "Cloud API": crm's built-in chat through frappe_whatsapp and a Meta account.
// `whatsappEnabled` keeps crm's meaning (Cloud API chat is usable), so crm's own WhatsApp UI only
// shows in Cloud API mode.
export const whatsappEnabled = ref(false)
export const isWhatsappInstalled = ref(false)
export const whatsappMode = ref('Click to Chat')
export const phoneCallingCode = ref('')
export const quickWhatsappEnabled = computed(() => whatsappMode.value === 'Click to Chat')
export const whatsappTabVisible = computed(
  () => whatsappEnabled.value || quickWhatsappEnabled.value,
)

const mode = createResource({
  url: 'abm_crm.api.quick_whatsapp.get_whatsapp_mode',
  cache: 'ABM WhatsApp Mode',
  auto: true,
  onSuccess: (data) => {
    whatsappMode.value = data?.mode || 'Click to Chat'
    phoneCallingCode.value = data?.calling_code || ''
    whatsappEnabled.value = Boolean(data?.cloud_enabled)
  },
})

const installed = createResource({
  url: 'crm.api.whatsapp.is_whatsapp_installed',
  cache: 'Is Whatsapp Installed',
  auto: true,
  onSuccess: (data) => {
    isWhatsappInstalled.value = Boolean(data)
  },
})

export function reloadWhatsappMode() {
  mode.reload()
}

// crm checks these once when the app loads, so a change made in another tab (or in desk) stayed
// hidden until a full reload. Re-check whenever the user comes back to the tab.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return
  mode.reload()
  installed.reload()
})

// International digits for wa.me / tel: links, e.g. "098765 43210" -> "919876543210".
// The server does the full validation; this is a fast best effort for list rows.
export function toWhatsappDigits(phone) {
  if (!phone) return ''
  let raw = String(phone).trim()
  if (raw.startsWith('+')) return raw.replace(/\D/g, '')
  let digits = raw.replace(/\D/g, '')
  if (digits.startsWith('00')) return digits.slice(2)
  digits = digits.replace(/^0+/, '')
  if (digits.length <= 10 && phoneCallingCode.value) return phoneCallingCode.value + digits
  return digits
}
