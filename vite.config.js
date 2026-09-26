import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'robots.txt', 'apple-touch-icon.png'],
      manifest: {
        name: 'ABV Fiesta - Aguardiente Blanco del Valle',
        short_name: 'ABV Fiesta',
        description: 'App campaña Fiesta Aguardiente Blanco del Valle. Toma foto, escoge escenario y compártela.',
        theme_color: '#002a7a',
        background_color: '#002a7a',
        display: 'standalone',
        orientation: 'landscape',
        start_url: '/',
        scope: '/',
        lang: 'es-CO',
        categories: ['entertainment', 'lifestyle', 'photo'],
        icons: [
          {
            src: '/assets/logo-oficial.png',
            sizes: 'any',
            type: 'image/png',
            purpose: 'any maskable'
          },
          {
            src: '/assets/logo-oficial.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any maskable'
          },
          {
            src: '/assets/logo-oficial.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any maskable'
          }
        ]
      },
      workbox: {
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        runtimeCaching: [
          {
            urlPattern: /\.(?:png|jpg|jpeg|svg|gif|webp|avif|ico)$/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'abv-static-images',
              expiration: {
                maxEntries: 60,
                maxAgeSeconds: 60 * 60 * 24 * 30
              },
              cacheableResponse: {
                statuses: [0, 200]
              }
            }
          },
          {
            urlPattern: /\.(?:js|css|woff2|woff|ttf|otf)$/i,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'abv-static-code',
              expiration: {
                maxEntries: 40,
                maxAgeSeconds: 60 * 60 * 24 * 15
              },
              cacheableResponse: {
                statuses: [0, 200]
              }
            }
          }
        ],
        globPatterns: ['**/*.{js,css,html,png,jpg,jpeg,svg,ico,woff2}'],
        globIgnores: ['**/node_modules/**/*', '**/*.map']
      },
      devOptions: {
        enabled: false
      }
    })
  ],
  server: {
    host: true,
    port: 5173
  }
})
