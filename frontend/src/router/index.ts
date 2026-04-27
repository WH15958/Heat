import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import ControlPanel from '../views/ControlPanel.vue'
import ExperimentPage from '../views/ExperimentPage.vue'
import HistoryPage from '../views/HistoryPage.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/control', name: 'control', component: ControlPanel },
    { path: '/experiment', name: 'experiment', component: ExperimentPage },
    { path: '/history', name: 'history', component: HistoryPage },
  ],
})

export default router
