import { BarChart, LineChart, type LineSeriesOption } from 'echarts/charts'
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, MarkAreaComponent, MarkLineComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, MarkAreaComponent, MarkLineComponent, DataZoomComponent, LineChart, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

export { init }
export type { ECharts, LineSeriesOption }
