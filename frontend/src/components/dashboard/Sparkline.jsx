function getPolylinePoints(values, width, height) {
  const minimum = Math.min(...values)
  const maximum = Math.max(...values)
  const range = maximum - minimum || 1

  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width
      const y = height - ((value - minimum) / range) * height
      return `${x},${y}`
    })
    .join(' ')
}

export default function Sparkline({ values, color = '#6877f5', width = 92, height = 34 }) {
  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <polyline
        points={getPolylinePoints(values, width, height)}
        fill="none"
        stroke={color}
        strokeWidth="2.2"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
