import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  normalizeDashboardVisibleWindow,
  panDashboardVisibleWindow,
  zoomDashboardVisibleWindow,
} from '../dashboard/dashboardSecurityModel.js'
import { backtestMinimumVisiblePoints } from './backtestPriceSignalChartModel'

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum)
}

export default function useBacktestChartViewport({
  chartWidth,
  plotLeft,
  plotWidth,
  totalPoints,
}) {
  const [visibleWindow, setVisibleWindow] = useState(null)
  const [isDragging, setIsDragging] = useState(false)
  const chartContainerRef = useRef(null)
  const dragRef = useRef(null)
  const previousTotalRef = useRef(totalPoints)
  const normalizedWindow = useMemo(
    () => normalizeDashboardVisibleWindow(visibleWindow, totalPoints),
    [totalPoints, visibleWindow],
  )
  const isFullView = !totalPoints || (
    normalizedWindow.start === 0
    && normalizedWindow.end === totalPoints - 1
  )

  useEffect(() => {
    if (previousTotalRef.current === totalPoints) return
    previousTotalRef.current = totalPoints
    setVisibleWindow(null)
    dragRef.current = null
    setIsDragging(false)
  }, [totalPoints])

  const getPointerPosition = useCallback((event) => {
    const bounds = chartContainerRef.current?.getBoundingClientRect()
    if (!bounds?.width || !bounds.height) return null
    const relativeX = event.clientX - bounds.left
    const relativeY = event.clientY - bounds.top
    return {
      bounds,
      chartX: (relativeX / bounds.width) * chartWidth,
      relativeX,
      relativeY,
    }
  }, [chartWidth])

  const resetVisibleWindow = useCallback(() => {
    dragRef.current = null
    setIsDragging(false)
    setVisibleWindow(null)
  }, [])

  const handleWheel = useCallback((event) => {
    if (!totalPoints || !event.deltaY) return
    event.preventDefault()
    event.stopPropagation()
    const position = getPointerPosition(event)
    if (!position) return

    const anchorRatio = clamp((position.chartX - plotLeft) / plotWidth, 0, 1)
    setVisibleWindow(zoomDashboardVisibleWindow({
      window: normalizedWindow,
      total: totalPoints,
      anchorRatio,
      deltaY: event.deltaY,
      minimumVisibleCandles: backtestMinimumVisiblePoints,
    }))
  }, [
    getPointerPosition,
    normalizedWindow,
    plotLeft,
    plotWidth,
    totalPoints,
  ])

  useEffect(() => {
    const chartElement = chartContainerRef.current
    if (!chartElement || !totalPoints) return undefined
    chartElement.addEventListener('wheel', handleWheel, { passive: false })
    return () => chartElement.removeEventListener('wheel', handleWheel)
  }, [handleWheel, totalPoints])

  const handlePointerDown = useCallback((event) => {
    if (event.button !== 0 || isFullView) return
    event.preventDefault()
    dragRef.current = {
      clientX: event.clientX,
      start: normalizedWindow.start,
      end: normalizedWindow.end,
    }
    setIsDragging(true)
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }, [isFullView, normalizedWindow])

  const handlePointerMove = useCallback((event) => {
    const drag = dragRef.current
    if (!drag || !totalPoints) return false
    event.preventDefault()
    const position = getPointerPosition(event)
    if (!position) return true

    const visibleCount = drag.end - drag.start + 1
    const renderedPlotWidth = position.bounds.width * (plotWidth / chartWidth)
    const pixelStep = Math.max(renderedPlotWidth / Math.max(visibleCount - 1, 1), 1)
    const shift = Math.round((drag.clientX - event.clientX) / pixelStep)
    if (!shift) return true

    setVisibleWindow(panDashboardVisibleWindow({
      window: { start: drag.start, end: drag.end },
      total: totalPoints,
      shift,
      minimumVisibleCandles: backtestMinimumVisiblePoints,
    }))
    return true
  }, [chartWidth, getPointerPosition, plotWidth, totalPoints])

  const handlePointerUp = useCallback((event) => {
    dragRef.current = null
    setIsDragging(false)
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }, [])

  return {
    chartContainerRef,
    getPointerPosition,
    handlePointerDown,
    handlePointerMove,
    handlePointerUp,
    isDragging,
    isFullView,
    normalizedWindow,
    resetVisibleWindow,
  }
}
