// Builds Frappe CRM's frontend (apps/crm/frontend) with abm_crm's overrides layered on top.
//
// Nothing is copied from crm. Any module that resolves to apps/crm/frontend/src/<path> is
// swapped for src_override/<path> when that file exists, for `@/` and relative imports alike.
// New files (pages, components) can also live in src_override and import crm modules with `@/`.
// Dependencies come from crm's node_modules, so run `yarn install` in apps/crm first.
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const HERE = import.meta.dirname
const CRM_FRONTEND = path.resolve(
  process.env.CRM_FRONTEND || path.join(HERE, '../../crm/frontend'),
)
const CRM_SRC = path.join(CRM_FRONTEND, 'src')
const OVERRIDE_SRC = path.join(HERE, 'src_override')
const APP_DIR = path.resolve(HERE, '../abm_crm')

const crmRequire = createRequire(path.join(CRM_FRONTEND, 'package.json'))
const importFromCrm = (id) => {
  let file
  try {
    file = crmRequire.resolve(id)
  } catch {
    // import-only subpath exports (e.g. frappe-ui/vite) are not visible to require.resolve
    file = path.join(CRM_FRONTEND, 'node_modules', id, 'index.js')
  }
  return import(pathToFileURL(file).href)
}

function abmOverrides() {
  const toCrmPath = (file) => path.join(CRM_SRC, path.relative(OVERRIDE_SRC, file))
  const toOverridePath = (file) =>
    path.join(OVERRIDE_SRC, path.relative(CRM_SRC, file))

  return {
    name: 'abm-crm-overrides',
    enforce: 'pre',
    async resolveId(source, importer, options) {
      if (!importer || source.startsWith('\0')) return null

      // `@/x` for a file that only exists in src_override (a new file) never resolves inside
      // crm. Vite applies the `@` alias before plugins run, so the source is already crm's path.
      if (source.startsWith(CRM_SRC + path.sep)) {
        const [sourcePath, query] = source.split('?')
        const base = toOverridePath(sourcePath)
        const found = ['', '.js', '.ts', '.vue', '/index.js'].find((ext) =>
          fs.existsSync(base + ext),
        )
        if (found !== undefined && fs.statSync(base + found).isFile()) {
          return query ? `${base + found}?${query}` : base + found
        }
      }

      const importerFile = importer.split('?')[0]
      const fromOverride = importerFile.startsWith(OVERRIDE_SRC + path.sep)

      // resolve as if the override file sat at its crm location, so relative imports and
      // bare packages (crm's node_modules) resolve the same way they do for the original
      let resolved = await this.resolve(
        source,
        fromOverride ? toCrmPath(importerFile) : importer,
        { ...options, skipSelf: true },
      )
      if (!resolved && fromOverride) {
        // a file that only exists in src_override, e.g. a new page
        resolved = await this.resolve(source, importer, { ...options, skipSelf: true })
      }
      if (!resolved || resolved.external) return resolved

      const [file, query] = resolved.id.split('?')
      if (file.startsWith(CRM_SRC + path.sep)) {
        const override = toOverridePath(file)
        if (fs.existsSync(override)) return query ? `${override}?${query}` : override
      }
      return resolved
    },
    transformIndexHtml(html) {
      return html.replaceAll('Frappe CRM', 'ABM CRM')
    },
  }
}

export default async ({ mode }) => {
  const { default: vue } = await importFromCrm('@vitejs/plugin-vue')
  const { default: vueJsx } = await importFromCrm('@vitejs/plugin-vue-jsx')
  const { VitePWA } = await importFromCrm('vite-plugin-pwa')
  const { default: frappeui } = await importFromCrm('frappe-ui/vite')
  const { default: tailwindcss } = await importFromCrm('tailwindcss')
  const { default: autoprefixer } = await importFromCrm('autoprefixer')
  return {
    root: CRM_FRONTEND,
    cacheDir: path.join(HERE, 'node_modules/.vite'),
    plugins: [
      frappeui({
        frappeProxy: true,
        lucideIcons: true,
        jinjaBootData: true,
        buildConfig: {
          outDir: path.join(APP_DIR, 'public/frontend'),
          baseUrl: '/assets/abm_crm/frontend/',
          indexHtmlPath: path.join(APP_DIR, 'www/crm.html'),
          emptyOutDir: true,
          sourcemap: true,
        },
      }),
      abmOverrides(),
      vue(),
      vueJsx(),
      VitePWA({
        registerType: 'autoUpdate',
        workbox: { maximumFileSizeToCacheInBytes: 10 * 1024 * 1024 },
        devOptions: { enabled: true },
        manifest: {
          display: 'standalone',
          name: 'ABM CRM',
          short_name: 'ABM CRM',
          start_url: '/crm',
          description: 'Custom CRM by ABM Tech',
          icons: [
            {
              src: '/assets/crm/manifest/manifest-icon-192.maskable.png',
              sizes: '192x192',
              type: 'image/png',
              purpose: 'any',
            },
            {
              src: '/assets/crm/manifest/manifest-icon-192.maskable.png',
              sizes: '192x192',
              type: 'image/png',
              purpose: 'maskable',
            },
            {
              src: '/assets/crm/manifest/manifest-icon-512.maskable.png',
              sizes: '512x512',
              type: 'image/png',
              purpose: 'any',
            },
            {
              src: '/assets/crm/manifest/manifest-icon-512.maskable.png',
              sizes: '512x512',
              type: 'image/png',
              purpose: 'maskable',
            },
          ],
        },
      }),
    ],
    css: {
      postcss: {
        plugins: [
          tailwindcss(path.join(HERE, 'tailwind.config.js')),
          autoprefixer(),
        ],
      },
    },
    resolve: {
      // keep in sync with apps/crm/frontend/vite.config.js
      alias: {
        '@': CRM_SRC,
        '@framework/ui': path.resolve(CRM_FRONTEND, '../../frappe/ui/src'),
      },
      dedupe: [
        'vue',
        'vue-router',
        'frappe-ui',
        'dompurify',
        'vuedraggable',
        '@tiptap/core',
        '@tiptap/pm',
        '@tiptap/vue-3',
        'prosemirror-model',
        'prosemirror-state',
        'prosemirror-view',
        'prosemirror-transform',
      ],
    },
    optimizeDeps: {
      include: [
        'feather-icons',
        'prosemirror-state',
        'prosemirror-view',
        'lowlight',
        'interactjs',
      ],
    },
    server: {
      fs: { allow: [path.resolve(HERE, '../..')] },
    },
  }
}
