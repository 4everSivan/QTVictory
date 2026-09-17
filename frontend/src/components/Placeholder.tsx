interface PlaceholderProps {
  label: string
}

export function Placeholder({ label }: PlaceholderProps) {
  return <div className="pane-placeholder">{label}</div>
}
