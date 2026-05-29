interface SliderProps {
  id: string
  label: string
  value: number
  min: number
  max: number
  step?: number
  display: string
  disabled?: boolean
  onChange: (value: number) => void
}

export function Slider({
  id,
  label,
  value,
  min,
  max,
  step,
  display,
  disabled,
  onChange,
}: SliderProps) {
  return (
    <div className="control-group">
      <div className="slider-header">
        <label htmlFor={id}>{label}</label>
        <span className="slider-indicator">{display}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  )
}
