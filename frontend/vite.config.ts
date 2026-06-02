import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
    }),
    Components({
      resolvers: [ElementPlusResolver()],
    }),
  ],
  build: {
    outDir: resolve(__dirname, '../src/web/static'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 550,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.replace(/\\/g, '/')

          if (normalizedId.includes('/node_modules/echarts/')) {
            if (normalizedId.includes('/echarts/charts/')) {
              return 'echarts-charts'
            }
            if (normalizedId.includes('/echarts/components/')) {
              return 'echarts-components'
            }
            if (normalizedId.includes('/echarts/features/')) {
              return 'echarts-features'
            }
            if (normalizedId.includes('/echarts/renderers/')) {
              return 'echarts-renderers'
            }
            return 'echarts-core'
          }

          if (normalizedId.includes('/node_modules/zrender/')) {
            return 'zrender'
          }

          if (normalizedId.includes('/node_modules/element-plus/')) {
            const componentMatch = normalizedId.match(/\/element-plus\/es\/components\/([^/]+)\//)
            if (componentMatch) {
              return `element-plus-${componentMatch[1]}`
            }
            if (normalizedId.includes('/element-plus/es/directives/')) {
              return 'element-plus-directives'
            }
            if (normalizedId.includes('/element-plus/es/hooks/')) {
              return 'element-plus-hooks'
            }
            if (normalizedId.includes('/element-plus/es/tokens/')) {
              return 'element-plus-tokens'
            }
            if (normalizedId.includes('/element-plus/es/utils/')) {
              return 'element-plus-utils'
            }
            return 'element-plus-core'
          }

          if (normalizedId.includes('/node_modules/@floating-ui/')) {
            return 'floating-ui'
          }

          if (normalizedId.includes('/node_modules/vue/') || normalizedId.includes('/node_modules/vue-router/')) {
            return 'vue-vendor'
          }
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
