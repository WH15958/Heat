import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
    { path: '/control', name: 'control', component: () => import('../views/ControlPanel.vue') },
    { path: '/experiment', name: 'experiment', component: () => import('../views/ExperimentPage.vue') },
    { path: '/campaigns', name: 'campaigns', component: () => import('../views/CampaignPage.vue') },
    { path: '/history', name: 'history', component: () => import('../views/HistoryPage.vue') },
  ],
})

export default router
