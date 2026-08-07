import { useCallback, useEffect, useRef, useState } from 'react'
import {
  normalizeDashboardVisibleWindow,
  panDashboardVisibleWindow,
  zoomDashboardVisibleWindow,
} from '../dashboard/dashboardSecurityModel'

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum)
}

export default function useMarketChartViewportInteraction({
  chartWidth,
  onVisibleWindowChange,
  onVisibleWindowReset,
  plotLeft,
  plotWidth,
  totalCandles,
  visibleWindow,
}) {
  const [isDragging, setIsDragging] = useState(false)
  const dragRef = useRef(null)
  const chartContainerRef = useRef(null)
  const normalizedWindow = normalizeDashboardVisibleWindow(visibleWindow, totalCandles)
  const isFullView = !totalCandles || (normalizedWindow.start === 0 && normalizedWindow.end === totalCandles - 1)

  const resetVisibleWindow = useCallback(() => {
    dragRef.current = null
    setIsDragging(false)
    onVisibleWindowReset?.()
  }, [onVisibleWindowReset])

  const getPointerChartPosition = useCallback((event) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    if (!bounds.width || !bounds.height) return null

    const relativeX = event.clientX - bounds.left
    return {
      bounds,
      chartX: (relativeX / bounds.width) * chartWidth,
    }
  }, [chartWidth])

  const handleViewportPointerMove = useCallback((event) => {
    if (!dragRef.current || !totalCandles) return
    event.preventDefault()

    const current = normalizeDashboardVisibleWindow(visibleWindow, totalCandles)
    const candleCount = current.end - current.start + 1
    if (candleCount >= totalCandles) return

    const position = getPointerChartPosition(event)
    if (!position) return

    const renderedPlotWidth = position.bounds.width * (plotWidth / chartWidth)
    const pixelStep = Math.max(renderedPlotWidth / Math.max(candleCount, 1), 1)
    const shift = Math.round((dragRef.current.clientX - event.clientX) / pixelStep)
    if (!shift) return

    onVisibleWindowChange?.(panDashboardVisibleWindow({
      window: {
        start: dragRef.current.start,
        end: dragRef.current.end,
      },
      total: totalCandles,
      shift,
    }))
  }, [
    chartWidth,
    getPointerChartPosition,
    onVisibleWindowChange,
    plotWidth,
    totalCandles,
    visibleWindow,
  ])

  const handlePointerDown = useCallback((event) => {
    if (!totalCandles || event.button !== 0) return
    event.preventDefault()
    const current = normalizeDashboardVisibleWindow(visibleWindow, totalCandles)
    dragRef.current = {
      clientX: event.clientX,
      start: current.start,
      end: current.end,
    }
    setIsDragging(true)
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }, [totalCandles, visibleWindow])

  const handlePointerUp = useCallback((event) => {
    dragRef.current = null
    setIsDragging(false)
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }, [])

  const handleWheel = useCallback((event) => {
    if (!totalCandles) return
    event.preventDefault()
    event.stopPropagation()
    if (!event.deltaY) return

    const position = getPointerChartPosition(event)
    if (!position) return

    const anchorRatio = clamp((position.chartX - plotLeft) / plotWidth, 0, 1)
    onVisibleWindowChange?.(zoomDashboardVisibleWindow({
      window: visibleWindow,
      total: totalCandles,
      anchorRatio,
      deltaY: event.deltaY,
    }))
  }, [
    getPointerChartPosition,
    onVisibleWindowChange,
    plotLeft,
    plotWidth,
    totalCandles,
    visibleWindow,
  ])

  useEffect(() => {
    const chartElement = chartContainerRef.current
    if (!chartElement || !totalCandles) return undefined

    chartElement.addEventListener('wheel', handleWheel, { passive: false })
    return () => {
      chartElement.removeEventListener('wheel', handleWheel)
    }
  }, [handleWheel, totalCandles])

  return {
    chartContainerRef,
    dragRef,
    getPointerChartPosition,
    handlePointerDown,
    handlePointerUp,
    handleViewportPointerMove,
    isDragging,
    isFullView,
    resetVisibleWindow,
  }
}
