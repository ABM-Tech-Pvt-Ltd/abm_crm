// Extends crm's Tailwind config so classes used in src_override are generated too.
// Loaded by Tailwind (jiti), not by Node directly, so crm's bare imports resolve.
import path from 'node:path'
import crmConfig from '../../crm/frontend/tailwind.config.js'

const CRM_FRONTEND = path.resolve(__dirname, '../../crm/frontend')

export default {
  ...crmConfig,
  content: [
    ...crmConfig.content.map((glob) => path.resolve(CRM_FRONTEND, glob)),
    path.resolve(__dirname, 'src_override/**/*.{vue,js,ts,jsx,tsx}'),
  ],
}
