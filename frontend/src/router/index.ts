import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import ControlPanel from '../views/ControlPanel.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/control', name: 'control', component: ControlPanel },
  ],
})

export default router
