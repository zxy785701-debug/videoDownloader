// Read presentation timings from the generated Tailwind tokens, not local constants.
export function motionDuration(name: string) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(`--ui-${name}`).trim()
  const amount = Number.parseFloat(value)
  if (!Number.isFinite(amount)) return 0
  return value.endsWith('ms') ? amount : amount * 1000
}

export function reducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
