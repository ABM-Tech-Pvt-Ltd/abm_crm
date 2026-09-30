import { createResource } from 'frappe-ui'
import { ref } from 'vue'

export const whatsappEnabled = ref(false)
export const isWhatsappInstalled = ref(false)

const enabled = createResource({
  url: 'crm.api.whatsapp.is_whatsapp_enabled',
  cache: 'Is Whatsapp Enabled',
  auto: true,
  onSuccess: (data) => {
    whatsappEnabled.value = Boolean(data)
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

// abm_crm: crm checks these once when the app loads, so a WhatsApp account activated in another tab
// (or in desk) stayed hidden until a full reload. Re-check whenever the user comes back to the tab.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return
  enabled.reload()
  installed.reload()
})
