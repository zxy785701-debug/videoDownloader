import { fileURLToPath } from 'node:url'
import { loadEnv } from 'vite'
import { buildSeoSite, optionsFromEnv, productionOrigin } from './build.ts'

const frontendDir = fileURLToPath(new URL('..', import.meta.url))
const options = optionsFromEnv(loadEnv('production', frontendDir, 'SEO_'))
await buildSeoSite(fileURLToPath(new URL('../site-dist/', import.meta.url)), options, true)
console.log('Standalone public site: frontend/site-dist (no API or learning data).')
console.log(productionOrigin(options.siteUrl) ? 'Production SEO metadata generated.' : 'Preview mode: noindex; set SEO_SITE_URL before publishing.')
